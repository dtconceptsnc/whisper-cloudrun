import os, json, tempfile, subprocess
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
import urllib.request

app = FastAPI(title="whisper.cpp API", version="1.0")

WHISPER_DIR = os.environ.get("WHISPER_DIR", "/app/whisper.cpp")
WHISPER_EXE = os.path.join(WHISPER_DIR, "build", "bin", "whisper-cli")
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "/app/models/ggml-base.en.bin")

@app.get("/healthz")
def healthz():
    return {"ok": True}

def _download_to_temp(url: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".audio")
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, path)
        return path
    except Exception as e:
        try: os.unlink(path)
        except: pass
        raise HTTPException(status_code=400, detail=f"Failed to fetch url: {e}")

@app.post("/transcribe")
async def transcribe(
    file: Optional[UploadFile] = File(default=None),
    url: Optional[str] = Form(default=None),
    model_path: Optional[str] = Form(default=None),
    diarize: Optional[bool] = Form(default=True),
    language: Optional[str] = Form(default=None),     # e.g. "en"
    translate: Optional[bool] = Form(default=False)   # whisper.cpp: -tr
):
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

        # Build command (matching your pattern + JSON for segments)
        cmd = [
            WHISPER_EXE,
            "-m", model,
            "-f", tmp_input,
            "-otxt",
            "-oj"
        ]
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

        return JSONResponse({
            "ok": (proc.returncode == 0),
            "cmd": " ".join(cmd),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "text": text,
            "segments": segments,
            "txt_exists": os.path.exists(txt_path),
            "json_exists": os.path.exists(json_path)
        })
    finally:
        if tmp_input and os.path.exists(tmp_input):
            for ext in ["", ".txt", ".json", ".srt", ".vtt", ".tsv"]:
                p = tmp_input + ext
                if os.path.exists(p):
                    try: os.unlink(p)
                    except: pass
