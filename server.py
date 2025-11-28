import os, json, tempfile, sqlite3, threading, time, uuid
import urllib.request
from urllib.parse import urlparse
from contextlib import contextmanager
from typing import Optional, Tuple, Dict, Any
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import requests
import numpy as np
import whisperx

# Prefer cuDNN/TF32 on GPU for speed (safe on L4 with cuDNN present)
try:
    import torch  # type: ignore

    if torch.cuda.is_available():
        torch.backends.cudnn.enabled = True
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
        torch.set_float32_matmul_precision("high")
except Exception:
    pass

try:
    from whisperx.diarize import DiarizationPipeline  # whisperx>=3.4.x
except ImportError:  # whisperx<=3.3 fallback
    DiarizationPipeline = getattr(whisperx, "DiarizationPipeline", None)

try:
    from whisperx.diarize import assign_word_speakers as _assign_word_speakers  # whisperx>=3.4.x
except ImportError:
    _assign_word_speakers = getattr(whisperx, "assign_word_speakers", None)

# Configuration
DB_PATH = os.environ.get("QUEUE_DB", "/tmp/whisper_jobs.sqlite3")
RESULT_TTL_SECONDS = int(os.environ.get("RESULT_TTL_SECONDS", "86400"))  # 1 day
WORKER_POLL_SEC = float(os.environ.get("WORKER_POLL_SEC", "1.0"))
CLEANUP_INTERVAL_SEC = int(os.environ.get("CLEANUP_INTERVAL_SEC", "3600"))  # 1 hour

WHISPERX_MODEL = os.environ.get("WHISPERX_MODEL", "tiny")
WHISPERX_DEVICE = os.environ.get("WHISPERX_DEVICE", "cuda")
WHISPERX_COMPUTE_TYPE = os.environ.get("WHISPERX_COMPUTE_TYPE", "float16")
WHISPERX_BATCH_SIZE = int(os.environ.get("WHISPERX_BATCH_SIZE", "32"))
WHISPERX_CACHE = os.environ.get("WHISPERX_CACHE", "/app/.cache/whisperx")
WHISPERX_DIARIZATION_MODEL = os.environ.get("WHISPERX_DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_HUB_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")

os.makedirs(WHISPERX_CACHE, exist_ok=True)

app = FastAPI(title="whisperX API", version="3.0")

# ========== SQLite Queue Implementation ==========

def _init_db():
    """Initialize SQLite database with jobs table"""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS jobs(
        id TEXT PRIMARY KEY,
        status TEXT NOT NULL,       -- queued|running|done|error
        payload TEXT NOT NULL,      -- json body
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        result TEXT                 -- json result (optional)
    );""")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_status_created ON jobs(status, created_at);")
    con.commit()
    con.close()

@contextmanager
def db():
    """Context manager for database connections"""
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    try:
        yield con
    finally:
        con.close()

def enqueue(payload: dict) -> str:
    """Add a new job to the queue"""
    jid = str(uuid.uuid4())
    now = time.time()
    with db() as con:
        con.execute("INSERT INTO jobs(id,status,payload,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (jid, "queued", json.dumps(payload), now, now))
    return jid

def next_job() -> Optional[tuple]:
    """Get next queued job and mark as running (atomic)"""
    with db() as con:
        con.execute("BEGIN IMMEDIATE;")  # lock row for update
        row = con.execute("SELECT id,payload FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            con.execute("COMMIT;")
            return None
        jid, payload = row
        con.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=?", (time.time(), jid))
        con.execute("COMMIT;")
        return jid, json.loads(payload)

def save_result(jid: str, result: dict, ok=True):
    """Save job result and update status"""
    with db() as con:
        con.execute("UPDATE jobs SET status=?, result=?, updated_at=? WHERE id=?",
                    ("done" if ok else "error", json.dumps(result), time.time(), jid))

def get_status(jid: str):
    """Get job status and result"""
    with db() as con:
        row = con.execute("SELECT status,result,created_at,updated_at FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            return None
        return {
            "status": row[0],
            "result": json.loads(row[1]) if row[1] else None,
            "created_at": row[2],
            "updated_at": row[3]
        }

def cleanup_old_jobs():
    """Remove jobs older than TTL"""
    cutoff = time.time() - RESULT_TTL_SECONDS
    with db() as con:
        deleted = con.execute("DELETE FROM jobs WHERE updated_at < ? AND status IN ('done','error')",
                             (cutoff,)).rowcount
        if deleted > 0:
            print(f"Cleaned up {deleted} old jobs")

# ========== Helper Functions ==========

def _download_to_temp(url: str) -> str:
    """Download URL to temporary file"""
    fd, path = tempfile.mkstemp(suffix=".audio")
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, path)
        return path
    except Exception as e:
        try:
            os.unlink(path)
        except:
            pass
        raise e

def _to_serializable(obj: Any):
    """Convert numpy/torch objects to JSON-serializable primitives"""
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    try:
        import torch  # type: ignore
        if isinstance(obj, torch.Tensor):
            return obj.tolist()
    except Exception:
        pass
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    return obj


def _strip_word_level(segments: Any):
    """Remove word-level details from segments to reduce payload size."""
    if not isinstance(segments, list):
        return segments
    cleaned = []
    for seg in segments:
        if isinstance(seg, dict):
            seg = {k: v for k, v in seg.items() if k != "words"}
        cleaned.append(seg)
    return cleaned


def _fmt_timestamp_ms(ms: int) -> str:
    """Format milliseconds to HH:MM:SS,mmm."""
    if ms < 0:
        ms = 0
    hrs, rem = divmod(ms, 3600000)
    mins, rem = divmod(rem, 60000)
    secs, millis = divmod(rem, 1000)
    return f"{int(hrs):02d}:{int(mins):02d}:{int(secs):02d},{int(millis):03d}"


def _segments_to_transcription(segments: list, include_words: bool):
    """Convert whisperx segments to target transcription schema."""
    transcription = []
    lines = []
    for seg in segments or []:
        start_ms = int(round(float(seg.get("start", 0)) * 1000))
        end_ms = int(round(float(seg.get("end", 0)) * 1000))
        text = (seg.get("text") or "").strip()
        speaker = str(seg.get("speaker") or "?")

        entry = {
            "timestamps": {
                "from": _fmt_timestamp_ms(start_ms),
                "to": _fmt_timestamp_ms(end_ms),
            },
            "offsets": {
                "from": start_ms,
                "to": end_ms,
            },
            "text": text,
            "speaker": speaker,
        }
        if include_words and isinstance(seg, dict) and seg.get("words"):
            entry["words"] = _to_serializable(seg["words"])

        transcription.append(entry)
        lines.append(f"({speaker}) {text}")

    combined_text = "\n".join(lines).strip()
    return transcription, combined_text


class WhisperXEngine:
    """Manage whisperX model, alignment, and diarization pipelines (GPU-only)."""

    def __init__(self):
        self.model = None
        self.model_lock = threading.Lock()
        self.align_models: Dict[str, Tuple[Any, Any]] = {}
        self.align_lock = threading.Lock()
        self.diarize_pipeline = None
        self.diarize_lock = threading.Lock()
        self.asr_device, self.asr_compute_type = self._resolve_asr_config()
        self.align_device = self.asr_device
        self.diarize_device = self.asr_device

    def _resolve_asr_config(self) -> Tuple[str, str]:
        """Pick ASR device/compute_type; ASR must run on CUDA."""
        requested_device = (WHISPERX_DEVICE or "").lower()
        if requested_device not in ("cuda", "gpu"):
            raise RuntimeError("ASR requires CUDA; set WHISPERX_DEVICE=cuda.")

        try:
            import torch  # type: ignore

            if not torch.cuda.is_available():
                raise RuntimeError("CUDA requested but not available (torch.cuda.is_available() is False).")
        except Exception as e:
            raise RuntimeError(f"Unable to verify CUDA availability: {e}")

        compute_type = WHISPERX_COMPUTE_TYPE
        return "cuda", compute_type

    def _ensure_model(self):
        if self.model is not None:
            return self.model
        with self.model_lock:
            if self.model is None:
                device = self.asr_device
                compute_type = self.asr_compute_type
                print(f"[whisperx] loading ASR model '{WHISPERX_MODEL}' on {device} (compute_type={compute_type}, downloads if missing, cache={WHISPERX_CACHE})")
                try:
                    self.model = whisperx.load_model(
                        WHISPERX_MODEL,
                        device=device,
                        compute_type=compute_type,
                        download_root=WHISPERX_CACHE,
                    )
                except ValueError as e:
                    if "float16" in str(e).lower() and compute_type.lower() == "float16":
                        print("[whisperx] float16 compute type not supported on CUDA backend; retrying with float32.")
                        compute_type = "float32"
                        self.asr_compute_type = compute_type
                        self.model = whisperx.load_model(
                            WHISPERX_MODEL,
                            device=device,
                            compute_type=compute_type,
                            download_root=WHISPERX_CACHE,
                        )
                    else:
                        raise
        return self.model

    def _get_align_model(self, language_code: Optional[str]):
        if not language_code:
            return None
        with self.align_lock:
            if language_code in self.align_models:
                return self.align_models[language_code]
            print(f"[whisperx] loading alignment model for language '{language_code}' on {self.align_device} (downloads if missing, cache={WHISPERX_CACHE})")
            align_model, metadata = whisperx.load_align_model(
                language_code=language_code,
                device=self.align_device,
                model_dir=WHISPERX_CACHE,
            )
            self.align_models[language_code] = (align_model, metadata)
            return align_model, metadata

    def _ensure_diarization(self):
        if self.diarize_pipeline is not None:
            return self.diarize_pipeline
        if not HF_TOKEN:
            raise RuntimeError("Diarization requires HF_TOKEN/HUGGINGFACE_HUB_TOKEN to be set.")
        with self.diarize_lock:
            if self.diarize_pipeline is None:
                if not DiarizationPipeline:
                    raise RuntimeError("Diarization not available: DiarizationPipeline missing (check whisperx version).")
                print(f"[whisperx] loading diarization pipeline '{WHISPERX_DIARIZATION_MODEL}' on {self.diarize_device} (downloads if missing, cache={WHISPERX_CACHE})")
                # DiarizationPipeline signature changed across whisperx versions; try known variants.
                init_errors = []
                for kwargs in [
                    {"model_name": WHISPERX_DIARIZATION_MODEL, "device": self.diarize_device, "use_auth_token": HF_TOKEN, "cache_dir": WHISPERX_CACHE},
                    {"model_name": WHISPERX_DIARIZATION_MODEL, "device": self.diarize_device, "use_auth_token": HF_TOKEN},
                    {"model_name": WHISPERX_DIARIZATION_MODEL, "device": self.diarize_device, "token": HF_TOKEN},
                ]:
                    try:
                        self.diarize_pipeline = DiarizationPipeline(**kwargs)
                        break
                    except TypeError as e:
                        init_errors.append(str(e))
                        continue
                if self.diarize_pipeline is None:
                    raise RuntimeError(f"Diarization initialization failed; tried multiple signatures. Errors: {init_errors}")
        return self.diarize_pipeline

    def transcribe(self, audio_path: str, diarize: bool, language: Optional[str], translate: bool, include_words: bool):
        """Run whisperX end-to-end (transcribe -> align -> optional diarization)."""
        audio = whisperx.load_audio(audio_path)
        model = self._ensure_model()
        task = "translate" if translate else "transcribe"
        language = language or "en"

        warnings = []
        result = model.transcribe(
            audio,
            batch_size=WHISPERX_BATCH_SIZE,
            language=language,
            task=task,
        )

        segments = result.get("segments", [])
        text = result.get("text", "").strip()
        detected_language = result.get("language", language)

        # Alignment improves timestamps, but skip when translating to avoid misalignment.
        if not translate:
            try:
                align_bundle = self._get_align_model(detected_language)
                if align_bundle:
                    align_model, metadata = align_bundle
                    aligned = whisperx.align(
                        segments,
                        align_model,
                        metadata,
                        audio,
                        self.align_device,
                        return_char_alignments=False,
                    )
                    segments = aligned.get("segments", segments)
            except Exception as e:
                warnings.append(f"alignment_failed: {e}")

        if diarize:
            try:
                diarization_pipeline = self._ensure_diarization()
                diarize_segments = diarization_pipeline(audio_path)
                if not _assign_word_speakers:
                    raise RuntimeError("assign_word_speakers not available (check whisperx version).")
                diarized = _assign_word_speakers(diarize_segments, {"segments": segments, "language": detected_language})
                segments = diarized.get("segments", segments) if isinstance(diarized, dict) else segments
            except Exception as e:
                warnings.append(f"diarization_failed: {e}")

        payload = {
            "text": None,  # placeholder until formatting below
            "segments": {
                "model": {
                    "type": WHISPERX_MODEL,
                    "multilingual": not WHISPERX_MODEL.endswith(".en"),
                },
                "params": {
                    "model": WHISPERX_MODEL,
                    "language": detected_language,
                    "translate": translate,
                    "compute_type": self.asr_compute_type,
                    "device": self.asr_device,
                },
                "result": {
                    "language": detected_language,
                },
                "transcription": [],
            },
            "warnings": warnings if warnings else None,
        }
        transcription, combined_text = _segments_to_transcription(
            _to_serializable(segments if include_words else _strip_word_level(segments)),
            include_words,
        )
        payload["segments"]["transcription"] = transcription
        payload["text"] = combined_text or text
        return payload


whisperx_engine = WhisperXEngine()

# ========== Background Workers ==========

def worker_loop():
    """Background worker that processes queued jobs"""
    print("Worker thread started")
    while True:
        job = next_job()
        if not job:
            time.sleep(WORKER_POLL_SEC)
            continue

        jid, payload = job
        print(f"Processing job {jid}")

        tmp = None
        try:
            # Prepare input file
            if payload.get("url"):
                tmp = _download_to_temp(payload["url"])
            elif payload.get("file_path"):
                # For file uploads saved to disk
                tmp = payload["file_path"]
            else:
                raise RuntimeError("No input file or URL provided")

            # Run transcription with whisperX (GPU)
            transcribed = whisperx_engine.transcribe(
                tmp,
                payload.get("diarize", True),
                payload.get("language") or "en",
                payload.get("translate", False),
                payload.get("include_words", False),
            )

            result = {"ok": True, **transcribed}

            # Save result to database
            save_result(jid, result, ok=True)
            print(f"Job {jid} completed: ok=True")

            # Optional callback to external service (e.g., n8n)
            callback_url = payload.get("callback_url")
            if callback_url:
                try:
                    callback_payload = {
                        "job_id": jid,
                        "status": "done",
                        **result
                    }
                    resp = requests.post(callback_url, json=callback_payload, timeout=30)
                    print(f"Callback sent to {callback_url}: status={resp.status_code}")
                except Exception as e:
                    print(f"Callback failed for job {jid}: {e}")
                    # Keep result in DB even if callback fails

        except Exception as e:
            error_msg = str(e)
            print(f"Job {jid} failed: {error_msg}")
            save_result(jid, {"ok": False, "error": error_msg}, ok=False)

            # Try callback even on error
            callback_url = payload.get("callback_url")
            if callback_url:
                try:
                    requests.post(callback_url, json={
                        "job_id": jid,
                        "status": "error",
                        "ok": False,
                        "error": error_msg
                    }, timeout=30)
                except:
                    pass
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except:
                    pass

def cleanup_loop():
    """Background task to cleanup old jobs"""
    print("Cleanup thread started")
    while True:
        time.sleep(CLEANUP_INTERVAL_SEC)
        try:
            cleanup_old_jobs()
        except Exception as e:
            print(f"Cleanup failed: {e}")

# ========== API Endpoints ==========

@app.get("/healthz")
def healthz():
    """Health check endpoint"""
    return {"ok": True}

@app.post("/transcribe/start")
async def start_transcription_job(
    callback_url: str = Form(...),
    file: Optional[UploadFile] = File(default=None),
    url: Optional[str] = Form(default=None),
    model_path: Optional[str] = Form(default=None),
    diarize: Optional[bool] = Form(default=False),
    language: Optional[str] = Form(default=None),
    translate: Optional[bool] = Form(default=False),
    include_words: Optional[bool] = Form(default=False),
):
    """
    Start an async transcription job.

    Parameters:
    - callback_url: URL to POST results when done (required)
    - file: Audio file upload (optional)
    - url: Audio file URL (optional)
    - model_path: Custom model path (optional)
    - diarize: Enable speaker diarization (default: true)
    - language: Language code (e.g., 'en', 'es')
    - translate: Translate to English (default: false)

    Returns job_id for status polling.
    """
    # Validate callback URL is provided and has valid format
    if not callback_url or not callback_url.strip():
        raise HTTPException(status_code=400, detail="callback_url is required")

    try:
        parsed = urlparse(callback_url)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail="callback_url must be a valid URL with scheme and domain")
        if parsed.scheme not in ["http", "https"]:
            raise HTTPException(status_code=400, detail="callback_url must use http or https scheme")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid callback_url: {str(e)}")

    if not file and not url:
        raise HTTPException(status_code=400, detail="Provide either 'file' or 'url'")

    # For Cloud Run, URL is recommended to avoid request timeout issues
    tmp_path = None
    try:
        if url:
            # Queue URL for download by worker
            payload = {
                "url": url,
                "model_path": model_path,
                "diarize": diarize,
                "language": language,
                "translate": translate,
                "include_words": include_words,
                "callback_url": callback_url
            }
        else:
            # Save uploaded file to temp location for worker to process
            suffix = os.path.splitext(file.filename or ".wav")[1]
            fd, tmp_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            with open(tmp_path, "wb") as f:
                f.write(await file.read())

            payload = {
                "file_path": tmp_path,
                "model_path": model_path,
                "diarize": diarize,
                "language": language,
                "translate": translate,
                "include_words": include_words,
                "callback_url": callback_url
            }

        jid = enqueue(payload)
        return JSONResponse({
            "job_id": jid,
            "status": "queued",
            "message": "Job queued for processing"
        })

    except Exception as e:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to queue job: {str(e)}")

@app.get("/transcribe/status/{job_id}")
def get_job_status(job_id: str):
    """
    Get status and result of a transcription job.

    Returns:
    - status: queued|running|done|error
    - result: transcription result (when done)
    """
    st = get_status(job_id)
    if not st:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        **st
    }

@app.post("/transcribe")
async def transcribe_sync(
    file: Optional[UploadFile] = File(default=None),
    url: Optional[str] = Form(default=None),
    model_path: Optional[str] = Form(default=None),
    diarize: Optional[bool] = Form(default=False),
    language: Optional[str] = Form(default=None),
    translate: Optional[bool] = Form(default=False),
    include_words: Optional[bool] = Form(default=False),
):
    """
    Synchronous transcription endpoint (legacy).

    WARNING: For Cloud Run, this may timeout on long audio files.
    Consider using /transcribe/start for async processing.
    """
    if not file and not url:
        raise HTTPException(status_code=400, detail="Provide a file OR a url.")

    tmp_input = None
    try:
        # Prepare input file
        if url:
            tmp_input = _download_to_temp(url)
        else:
            suffix = os.path.splitext(file.filename or ".wav")[1]
            fd, tmp_input = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            with open(tmp_input, "wb") as f:
                f.write(await file.read())

        transcribed = whisperx_engine.transcribe(
            tmp_input,
            diarize,
            language or "en",
            translate,
            include_words,
        )

        return JSONResponse({"ok": True, **transcribed})

    finally:
        if tmp_input and os.path.exists(tmp_input):
            try:
                os.unlink(tmp_input)
            except:
                pass

@app.get("/queue/stats")
def queue_stats():
    """Get queue statistics"""
    with db() as con:
        stats = {}
        for status in ["queued", "running", "done", "error"]:
            count = con.execute("SELECT COUNT(*) FROM jobs WHERE status=?", (status,)).fetchone()[0]
            stats[status] = count
        return stats

# ========== Startup ==========

# Initialize database and start background workers
_init_db()
threading.Thread(target=worker_loop, daemon=True).start()
threading.Thread(target=cleanup_loop, daemon=True).start()

print(f"WhisperX API started")
print(f"Worker polling interval: {WORKER_POLL_SEC}s")
print(f"Result TTL: {RESULT_TTL_SECONDS}s")
print(f"WhisperX model: {WHISPERX_MODEL}")
print(f"Requested device: {WHISPERX_DEVICE}, requested compute_type: {WHISPERX_COMPUTE_TYPE}")
print(f"ASR device: {whisperx_engine.asr_device}, compute_type: {whisperx_engine.asr_compute_type}, batch_size: {WHISPERX_BATCH_SIZE}")
print(f"Decode opts: batch_size={WHISPERX_BATCH_SIZE}, task=translate|transcribe (runtime), language=runtime")
print(f"Alignment device: {whisperx_engine.align_device}, diarization device: {whisperx_engine.diarize_device}")
print(f"Cache dir: {WHISPERX_CACHE}")
