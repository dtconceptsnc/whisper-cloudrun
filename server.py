import os, json, tempfile, subprocess, sqlite3, threading, time, uuid
import urllib.request
from contextlib import contextmanager
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import requests

# Configuration
DB_PATH = os.environ.get("QUEUE_DB", "/tmp/whisper_jobs.sqlite3")
RESULT_TTL_SECONDS = int(os.environ.get("RESULT_TTL_SECONDS", "86400"))  # 1 day
WORKER_POLL_SEC = float(os.environ.get("WORKER_POLL_SEC", "1.0"))
CLEANUP_INTERVAL_SEC = int(os.environ.get("CLEANUP_INTERVAL_SEC", "3600"))  # 1 hour

WHISPER_DIR = os.environ.get("WHISPER_DIR", "/app/whisper.cpp")
# Dockerfile uses make build: whisper.cpp/main
# If you switch to CMake build, use: os.path.join(WHISPER_DIR, "build", "bin", "whisper-cli")
WHISPER_EXE = os.environ.get("WHISPER_EXE", os.path.join(WHISPER_DIR, "main"))
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "/app/models/ggml-base.en.bin")

app = FastAPI(title="whisper.cpp API", version="2.0")

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

def _run_whisper(tmp_input: str, model: str, diarize: bool, language: Optional[str], translate: bool):
    """Execute whisper.cpp and return results"""
    cmd = [WHISPER_EXE, "-m", model, "-f", tmp_input, "-otxt", "-oj"]
    if diarize:
        cmd.append("--diarize")
    if translate:
        cmd.append("-tr")
    if language:
        cmd.extend(["-l", language])

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    base = tmp_input
    txt_path = base + ".txt"
    json_path = base + ".json"

    text = ""
    segments = None

    if os.path.exists(txt_path):
        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read().strip()

    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8", errors="ignore") as f:
                j = json.load(f)
                segments = j.get("segments", j)
        except Exception:
            segments = None

    # Cleanup temp artifacts
    for ext in ["", ".txt", ".json", ".srt", ".vtt", ".tsv"]:
        p = base + ext
        if os.path.exists(p):
            try:
                os.unlink(p)
            except:
                pass

    return proc.returncode == 0, " ".join(cmd), proc.stderr, text, segments

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

        try:
            # Prepare input file
            tmp = None
            if payload.get("url"):
                tmp = _download_to_temp(payload["url"])
            elif payload.get("file_path"):
                # For file uploads saved to disk
                tmp = payload["file_path"]
            else:
                raise RuntimeError("No input file or URL provided")

            # Run transcription
            model = payload.get("model_path", DEFAULT_MODEL)
            if not os.path.exists(model):
                raise RuntimeError(f"Model not found: {model}")

            ok, cmd, stderr, text, segments = _run_whisper(
                tmp, model,
                payload.get("diarize", True),
                payload.get("language"),
                payload.get("translate", False)
            )

            result = {
                "ok": ok,
                "cmd": cmd,
                "stderr": stderr,
                "text": text,
                "segments": segments
            }

            # Save result to database
            save_result(jid, result, ok=ok)
            print(f"Job {jid} completed: ok={ok}")

            # Optional callback to external service (e.g., n8n)
            callback_url = payload.get("callback_url")
            if callback_url:
                try:
                    callback_payload = {
                        "job_id": jid,
                        "status": "done" if ok else "error",
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
    file: Optional[UploadFile] = File(default=None),
    url: Optional[str] = Form(default=None),
    model_path: Optional[str] = Form(default=None),
    diarize: Optional[bool] = Form(default=True),
    language: Optional[str] = Form(default=None),
    translate: Optional[bool] = Form(default=False),
    callback_url: Optional[str] = Form(default=None),
):
    """
    Start an async transcription job.

    Parameters:
    - file: Audio file upload (optional)
    - url: Audio file URL (optional)
    - model_path: Custom model path (optional)
    - diarize: Enable speaker diarization (default: true)
    - language: Language code (e.g., 'en', 'es')
    - translate: Translate to English (default: false)
    - callback_url: URL to POST results when done (optional)

    Returns job_id for status polling.
    """
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
    diarize: Optional[bool] = Form(default=True),
    language: Optional[str] = Form(default=None),
    translate: Optional[bool] = Form(default=False)
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

        # Resolve model
        model = model_path or DEFAULT_MODEL
        if not os.path.exists(model):
            raise HTTPException(status_code=400, detail=f"Model not found: {model}")

        # Run transcription
        ok, cmd, stderr, text, segments = _run_whisper(
            tmp_input, model, diarize, language, translate
        )

        return JSONResponse({
            "ok": ok,
            "cmd": cmd,
            "stderr": stderr,
            "text": text,
            "segments": segments
        })

    finally:
        if tmp_input and os.path.exists(tmp_input):
            for ext in ["", ".txt", ".json", ".srt", ".vtt", ".tsv"]:
                p = tmp_input + ext
                if os.path.exists(p):
                    try:
                        os.unlink(p)
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

print(f"Whisper API started")
print(f"Worker polling interval: {WORKER_POLL_SEC}s")
print(f"Result TTL: {RESULT_TTL_SECONDS}s")
print(f"Whisper executable: {WHISPER_EXE}")
print(f"Default model: {DEFAULT_MODEL}")
