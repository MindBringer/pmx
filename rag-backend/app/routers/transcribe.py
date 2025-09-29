# app/transcribe.py
# FastAPI Router: Transcribe (Sync + Async + Jobs + Env)
# - kompatibel zu deinem bisherigen Sync-Endpoint
# - neu: /transcribe/async mit file_url, BackgroundTasks, einfachem Jobstore
# - neu: /transcribe/jobs/{id} (Polling) + optional callback_url
# - neu: /transcribe/env (ENV-Werte einsehen)

import logging
import os
import uuid
import shutil
import tempfile
import subprocess
from typing import List, Optional, Tuple, Dict, Any

import numpy as np
import soundfile as sf
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, AnyHttpUrl
from faster_whisper import WhisperModel

# --------- Konfiguration über ENV ----------
ASR_MODEL               = os.getenv("ASR_MODEL", "medium")
ASR_DEVICE              = os.getenv("DEVICE", "cuda")  # "cuda" | "cpu"
ASR_COMPUTE_TYPE        = os.getenv("ASR_COMPUTE_TYPE", "float16")  # "float16"|"int8_float16"|"int8"|"float32"
ASR_BEAM_SIZE           = int(os.getenv("ASR_BEAM_SIZE", "5"))
ASR_BEST_OF             = int(os.getenv("ASR_BEST_OF", "1"))
ASR_TEMPERATURE         = float(os.getenv("ASR_TEMPERATURE", "0.0"))
ASR_INITIAL_PROMPT      = os.getenv("ASR_INITIAL_PROMPT", "").strip()
ASR_CHUNK_LENGTH        = int(os.getenv("ASR_CHUNK_LENGTH", "120"))  # Sekunden (120 empfohlen)
ASR_VAD_FILTER          = os.getenv("ASR_VAD_FILTER", "true").lower() in ("1", "true", "yes", "on")
ASR_NO_SPEECH_THRESHOLD = float(os.getenv("ASR_NO_SPEECH_THRESHOLD", "0.8"))
ASR_LOG_PROB_THRESHOLD  = float(os.getenv("ASR_LOG_PROB_THRESHOLD", "-1.0"))
FFMPEG_BIN              = os.getenv("FFMPEG_BIN", "ffmpeg")

JOBS_DIR                = os.getenv("JOBS_DIR", "/data/jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

# --------- FastAPI Router ----------
router = APIRouter(prefix="/transcribe", tags=["audio"])
logger = logging.getLogger(__name__)

# --------- Whisper Model Cache ----------
_whisper_model: Optional[WhisperModel] = None

def get_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel(
            ASR_MODEL, device=ASR_DEVICE, compute_type=ASR_COMPUTE_TYPE
        )
        logger.info("Loaded Whisper model=%s device=%s type=%s", ASR_MODEL, ASR_DEVICE, ASR_COMPUTE_TYPE)
    return _whisper_model

@router.on_event("startup")
def preload_model() -> None:
    try:
        get_model()
    except Exception:  # pragma: no cover
        logger.exception("Failed to preload Whisper model during startup")

# --------- Helpers ----------
def _ffmpeg_wav_mono16k(inp_path: str, out_path: str) -> None:
    """Konvertiert Audio zuverlässig nach WAV mono/16k, ohne Längen-Cut."""
    cmd = [FFMPEG_BIN, "-y", "-i", inp_path, "-ac", "1", "-ar", "16000", "-vn", out_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed: {proc.stderr.decode(errors='ignore') or proc.stdout.decode(errors='ignore')}"
        )

def _audio_duration_ms(wav_path: str) -> int:
    data, sr = sf.read(wav_path)
    n = data.shape[0] if isinstance(data, np.ndarray) else len(data)
    return int(n * 1000 / sr)

def _collect_transcript(whisper_segments) -> Tuple[str, List[dict]]:
    text_total: List[str] = []
    segments: List[dict] = []
    for s in whisper_segments:
        stext = (s.text or "").strip()
        if stext:
            text_total.append(stext)
        segments.append({
            "start_ms": int((getattr(s, "start", 0.0) or 0.0) * 1000),
            "end_ms":   int((getattr(s, "end", 0.0)   or 0.0) * 1000),
            "text":     stext
        })
    return ("".join(text_total)).strip(), segments

def _job_path(jid: str) -> str:
    return os.path.join(JOBS_DIR, f"{jid}.json")

def _job_save(j: Dict[str, Any]) -> None:
    import json
    with open(_job_path(j["id"]), "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False)

def _job_load(jid: str) -> Dict[str, Any]:
    import json
    p = _job_path(jid)
    if not os.path.exists(p):
        raise HTTPException(404, "job not found")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def _download_to_tmp(url: str) -> str:
    # Requests ist bewusst nur hier verwendet; falls nicht in requirements, bitte hinzufügen.
    import requests
    tmpdir = tempfile.mkdtemp(prefix="transc_")
    dst = os.path.join(tmpdir, "input.bin")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dst

# --------- Response Models ----------
class TranscribeOut(BaseModel):
    text: str
    segments: List[dict]
    info: dict
    summary: Optional[dict] = None
    debug: Optional[dict]  = None

class TranscribeAsyncIn(BaseModel):
    file_url: AnyHttpUrl
    language: Optional[str] = None
    vad_filter: Optional[bool] = None
    chunk_length: Optional[int] = None
    beam_size: Optional[int] = None
    best_of: Optional[int] = None
    temperature: Optional[float] = None
    initial_prompt: Optional[str] = None
    no_speech_threshold: Optional[float] = None
    log_prob_threshold: Optional[float] = None
    callback_url: Optional[AnyHttpUrl] = None
    meta: Optional[dict] = None  # wird ungeprüft zurückgegeben (nützlich für n8n)

# --------- SYNC Endpoint ----------
@router.post("", response_model=TranscribeOut)
async def transcribe_endpoint(
    file: UploadFile = File(...),

    language: Optional[str] = Form(default=None),      # z.B. "de"
    vad_filter: Optional[bool] = Form(default=None),   # override
    chunk_length: Optional[int] = Form(default=None),  # override Sekunden

    beam_size: Optional[int] = Form(default=None),
    best_of: Optional[int] = Form(default=None),
    temperature: Optional[float] = Form(default=None),
    initial_prompt: Optional[str] = Form(default=None),

    no_speech_threshold: Optional[float] = Form(default=None),
    log_prob_threshold: Optional[float] = Form(default=None),
):
    """
    Transkribiert die Datei synchron – robust (keine 24s-Kappung), geeignet für kleine/mittlere Längen.
    """
    workdir = tempfile.mkdtemp(prefix="transc_")
    src_path = os.path.join(workdir, f"src_{uuid.uuid4().hex}")
    wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")

    # Defaults aus ENV + Form-Overrides
    use_vad = ASR_VAD_FILTER if vad_filter is None else bool(vad_filter)
    chunk_len = ASR_CHUNK_LENGTH if (chunk_length is None or chunk_length <= 0) else int(chunk_length)

    eff_beam_size = ASR_BEAM_SIZE if (beam_size is None or beam_size <= 0) else int(beam_size)
    eff_best_of = ASR_BEST_OF if (best_of is None or best_of <= 0) else int(best_of)
    eff_temperature = ASR_TEMPERATURE if (temperature is None) else float(temperature)
    eff_initial_prompt = (initial_prompt if (initial_prompt is not None and initial_prompt.strip()) else ASR_INITIAL_PROMPT)
    eff_no_speech_threshold = ASR_NO_SPEECH_THRESHOLD if (no_speech_threshold is None) else float(no_speech_threshold)
    eff_log_prob_threshold = ASR_LOG_PROB_THRESHOLD if (log_prob_threshold is None) else float(log_prob_threshold)

    try:
        # Datei persistieren (streamed read)
        with open(src_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        # Reencode → WAV mono/16k
        _ffmpeg_wav_mono16k(src_path, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        # Transcribe
        model = get_model()
        it, info = model.transcribe(
            wav_path,
            language=language or None,
            vad_filter=use_vad,
            no_speech_threshold=eff_no_speech_threshold,
            log_prob_threshold=eff_log_prob_threshold,
            chunk_length=chunk_len if chunk_len > 0 else None,
            beam_size=eff_beam_size,
            best_of=eff_best_of,
            temperature=eff_temperature,
            initial_prompt=(eff_initial_prompt or None),
        )
        whisper_segments = list(it)
        full_text, segments = _collect_transcript(whisper_segments)

        summary = {
            "tldr": [],
            "entscheidungen": [],
            "aktionen": [],
            "offene_fragen": [],
            "risiken": [],
            "zeitachse": [],
            "redeanteile": [],
        }

        out = {
            "text": full_text,
            "segments": segments,
            "info": {
                "language": getattr(info, "language", None),
                "duration_ms": dur_ms,
                "model": ASR_MODEL,
                "device": ASR_DEVICE,
                "compute_type": ASR_COMPUTE_TYPE,
                "vad_filter": use_vad,
                "chunk_length_s": chunk_len,
                "beam_size": eff_beam_size,
                "best_of": eff_best_of,
                "temperature": eff_temperature,
                "used_initial_prompt": bool(eff_initial_prompt),
                "no_speech_threshold": eff_no_speech_threshold,
                "log_prob_threshold": eff_log_prob_threshold,
            },
            "summary": summary,
            "debug": {
                "input_filename": file.filename,
                "workdir": os.path.basename(workdir),
            },
        }
        return JSONResponse(out)
    except Exception as e:
        logger.exception("transcribe failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

# --------- ASYNC Endpoints ----------
@router.post("/async")
def transcribe_async(body: TranscribeAsyncIn, bg: BackgroundTasks):
    """
    Startet einen Transkriptionsjob asynchron (Input via file_url).
    Antwortet sofort mit job_id. Ergebnis via GET /transcribe/jobs/{id} oder optional callback_url.
    """
    jid = uuid.uuid4().hex
    job = {
        "id": jid,
        "status": "queued",
        "created_at": int(__import__("time").time()),
        "updated_at": int(__import__("time").time()),
        "request": body.dict(),
        "result": None,
        "error": None,
    }
    _job_save(job)
    bg.add_task(_do_transcribe_job, jid)
    return {"job_id": jid, "status": "queued"}

@router.get("/jobs/{job_id}")
def transcribe_job_status(job_id: str):
    return _job_load(job_id)

def _post_callback(url: str, payload: dict) -> None:
    try:
        import requests
        requests.post(str(url), json=payload, timeout=15)
    except Exception:
        logger.warning("callback post failed", exc_info=True)

def _do_transcribe_job(job_id: str) -> None:
    """Wird im BackgroundTask ausgeführt."""
    try:
        j = _job_load(job_id)
        req = j.get("request") or {}
        src = _download_to_tmp(req["file_url"])
        workdir = tempfile.mkdtemp(prefix="transc_")
        wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")

        # effektive Parameter wie im Sync
        use_vad = ASR_VAD_FILTER if (req.get("vad_filter") is None) else bool(req.get("vad_filter"))
        chunk_len = ASR_CHUNK_LENGTH if (not req.get("chunk_length") or int(req["chunk_length"]) <= 0) else int(req["chunk_length"])
        eff_beam_size = ASR_BEAM_SIZE if (not req.get("beam_size") or int(req["beam_size"]) <= 0) else int(req["beam_size"])
        eff_best_of = ASR_BEST_OF if (not req.get("best_of") or int(req["best_of"]) <= 0) else int(req["best_of"])
        eff_temperature = ASR_TEMPERATURE if (req.get("temperature") is None) else float(req["temperature"])
        eff_initial_prompt = (req.get("initial_prompt") or ASR_INITIAL_PROMPT).strip()
        eff_no_speech_threshold = ASR_NO_SPEECH_THRESHOLD if (req.get("no_speech_threshold") is None) else float(req["no_speech_threshold"])
        eff_log_prob_threshold = ASR_LOG_PROB_THRESHOLD if (req.get("log_prob_threshold") is None) else float(req["log_prob_threshold"])

        # Reencode
        _ffmpeg_wav_mono16k(src, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        model = get_model()
        it, info = model.transcribe(
            wav_path,
            language=req.get("language") or None,
            vad_filter=use_vad,
            no_speech_threshold=eff_no_speech_threshold,
            log_prob_threshold=eff_log_prob_threshold,
            chunk_length=chunk_len if chunk_len > 0 else None,
            beam_size=eff_beam_size,
            best_of=eff_best_of,
            temperature=eff_temperature,
            initial_prompt=(eff_initial_prompt or None),
        )
        whisper_segments = list(it)
        full_text, segments = _collect_transcript(whisper_segments)

        result = {
            "text": full_text,
            "segments": segments,
            "info": {
                "language": getattr(info, "language", None),
                "duration_ms": dur_ms,
                "model": ASR_MODEL,
                "device": ASR_DEVICE,
                "compute_type": ASR_COMPUTE_TYPE,
                "vad_filter": use_vad,
                "chunk_length_s": chunk_len,
                "beam_size": eff_beam_size,
                "best_of": eff_best_of,
                "temperature": eff_temperature,
                "used_initial_prompt": bool(eff_initial_prompt),
                "no_speech_threshold": eff_no_speech_threshold,
                "log_prob_threshold": eff_log_prob_threshold,
            },
            "summary": {
                "tldr": [], "entscheidungen": [], "aktionen": [], "offene_fragen": [],
                "risiken": [], "zeitachse": [], "redeanteile": [],
            },
            "debug": {
                "source_url": req.get("file_url"),
                "workdir": os.path.basename(workdir),
            },
            "meta": req.get("meta") or {},
        }

        j.update({"status": "done", "result": result, "updated_at": int(__import__("time").time())})
        _job_save(j)

        if req.get("callback_url"):
            _post_callback(req["callback_url"], {"job_id": j["id"], "status": "done", "result": result})

        # cleanup
        try:
            shutil.rmtree(os.path.dirname(src), ignore_errors=True)
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

    except Exception as e:
        logger.exception("transcribe job failed")
        try:
            j = _job_load(job_id)
            j.update({"status": "error", "error": str(e), "updated_at": int(__import__("time").time())})
            _job_save(j)
            req = j.get("request") or {}
            if req.get("callback_url"):
                _post_callback(req["callback_url"], {"job_id": j["id"], "status": "error", "error": str(e)})
        except Exception:
            pass

# --------- Debug / ENV ----------
@router.get("/env")
def show_env():
    keys = [k for k in os.environ.keys() if k.startswith("ASR_") or k in ("DEVICE", "FFMPEG_BIN")]
    return {k: os.getenv(k) for k in sorted(keys)}
