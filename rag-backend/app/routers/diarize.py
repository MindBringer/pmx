# app/diarize.py
# FastAPI Router: Diarization (Sync + Async + Jobs + Env)
# Backends:
#   - "vad"       : Silero-VAD (schnell, CPU)
#   - "pyannote"  : pyannote.audio (präzise, langsam)
# Einheitliche Ausgabe: segments[{start_ms, end_ms, spk}]

import os
import uuid
import json
import shutil
import tempfile
import logging
import subprocess
from typing import Optional, List, Dict, Any

import numpy as np
import soundfile as sf
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, AnyHttpUrl

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diarize", tags=["audio"])

# ----------------- ENV / Defaults -----------------
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
DIAR_BACKEND = os.getenv("DIAR_BACKEND", "vad").lower()

# Für pyannote (optional)
DIAR_MODEL = os.getenv("DIAR_MODEL", "pyannote/speaker-diarization-3.1")
DIAR_AUTH_TOKEN = os.getenv("DIAR_AUTH_TOKEN", "").strip()

# Feintuning (beide Backends)
DIAR_COLLAR_SEC = float(os.getenv("DIAR_COLLAR_SEC", "0.05"))
DIAR_MIN_SPEECH_SEC = float(os.getenv("DIAR_MIN_SPEECH_SEC", "0.2"))

# Jobs
JOBS_DIR = os.getenv("JOBS_DIR", "/data/jobs")
os.makedirs(JOBS_DIR, exist_ok=True)


# ----------------- Helpers -----------------
def _ffmpeg_wav_mono16k(inp_path: str, out_path: str) -> None:
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


def _job_path(jid: str) -> str:
    return os.path.join(JOBS_DIR, f"{jid}.diar.json")


def _job_save(j: Dict[str, Any]) -> None:
    with open(_job_path(j["id"]), "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False)


def _job_load(jid: str) -> Dict[str, Any]:
    p = _job_path(jid)
    if not os.path.exists(p):
        raise HTTPException(404, "job not found")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _download_to_tmp(url: str) -> str:
    import requests
    tmpdir = tempfile.mkdtemp(prefix="diar_")
    dst = os.path.join(tmpdir, "input.bin")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dst


# ----------------- Silero-VAD Backend -----------------
# ----------------- Silero-VAD Backend -----------------
_silero_model = None
_silero_utils = None

def _load_silero():
    """Lädt Modell + Utils aus torch.hub"""
    global _silero_model, _silero_utils
    if _silero_model is not None:
        return _silero_model, _silero_utils
    import torch
    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        trust_repo=True,
    )
    model.eval()
    logger.info("Loaded Silero-VAD via torch.hub")
    _silero_model, _silero_utils = model, utils
    return model, utils


def _run_diarization_vad(wav_path: str) -> List[Dict[str, Any]]:
    """Führt schnelle VAD-Segmentierung mit Silero-VAD aus."""
    model, utils = _load_silero()

    # utils kann Dict oder Tuple sein → beide Varianten behandeln
    if isinstance(utils, dict):
        read_audio = utils.get("read_audio")
        get_speech_timestamps = utils.get("get_speech_timestamps")
    elif isinstance(utils, (list, tuple)):
        # Sicherstellen, dass richtige Indizes gewählt werden
        read_audio = utils[0]
        # neuere Version: get_speech_timestamps an Index 2
        get_speech_timestamps = utils[2] if len(utils) > 2 else utils[1]
    else:
        raise RuntimeError(f"Unexpected Silero utils type: {type(utils)}")

    # 1) Audio lesen (16 kHz mono)
    wav = read_audio(wav_path, sampling_rate=16000)

    # 2) Sprachsegmente berechnen
    ts_list = get_speech_timestamps(
        wav,
        model,
        sampling_rate=16000,
        threshold=0.5,
        min_speech_duration_ms=int(DIAR_MIN_SPEECH_SEC * 1000),
        min_silence_duration_ms=500,
        speech_pad_ms=int(DIAR_COLLAR_SEC * 1000),
    )

    # 3) In vereinheitlichtes Format umwandeln
    segments: List[Dict[str, Any]] = []
    for ts in ts_list:
        start_ms = int(ts["start"] * 1000 / 16000)
        end_ms = int(ts["end"] * 1000 / 16000)
        if end_ms <= start_ms:
            continue
        segments.append({"start_ms": start_ms, "end_ms": end_ms, "spk": "SPEECH"})
    return segments


# ----------------- Pyannote Backend (optional) -----------------
_pyannote = None


def _load_pyannote():
    global _pyannote
    if _pyannote is not None:
        return _pyannote
    if not DIAR_AUTH_TOKEN:
        raise HTTPException(503, detail="DIAR_AUTH_TOKEN missing for pyannote backend.")
    try:
        from pyannote.audio import Pipeline
    except Exception as e:
        raise HTTPException(503, detail=f"pyannote.audio not available: {e}")
    _pyannote = Pipeline.from_pretrained(DIAR_MODEL, use_auth_token=DIAR_AUTH_TOKEN)
    logger.info("Loaded pyannote pipeline model=%s", DIAR_MODEL)
    return _pyannote


def _run_diarization_pyannote(wav_path: str, max_speakers: Optional[int]) -> List[Dict[str, Any]]:
    pipeline = _load_pyannote()
    diar = pipeline(wav_path, num_speakers=max_speakers) if max_speakers else pipeline(wav_path)
    segments: List[Dict[str, Any]] = []
    speaker_map: Dict[str, str] = {}
    for turn, _, speaker in diar.itertracks(yield_label=True):
        spk_label = speaker_map.setdefault(speaker, f"S{len(speaker_map)+1}")
        start_ms = int(1000 * float(turn.start))
        end_ms = int(1000 * float(turn.end))
        if end_ms <= start_ms:
            continue
        segments.append({"start_ms": start_ms, "end_ms": end_ms, "spk": spk_label})
    segments.sort(key=lambda s: (s["start_ms"], s["end_ms"]))
    return segments


# ----------------- Models -----------------
class DiarizeOut(BaseModel):
    segments: List[dict]
    info: dict
    speech_ratios: Optional[List[dict]] = None
    debug: Optional[dict] = None


class DiarizeAsyncIn(BaseModel):
    file_url: AnyHttpUrl
    max_speakers: Optional[int] = None
    callback_url: Optional[AnyHttpUrl] = None
    meta: Optional[dict] = None


# ----------------- SYNC -----------------
@router.post("", response_model=DiarizeOut)
async def diarize_endpoint(
    file: UploadFile = File(...),
    max_speakers: Optional[int] = Form(default=None),
):
    workdir = tempfile.mkdtemp(prefix="diar_")
    src_path = os.path.join(workdir, f"src_{uuid.uuid4().hex}")
    wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")
    try:
        with open(src_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        _ffmpeg_wav_mono16k(src_path, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        if DIAR_BACKEND == "vad":
            segments = _run_diarization_vad(wav_path)
            ratios = []
            backend_info = {"backend": "silero-vad"}
        elif DIAR_BACKEND == "pyannote":
            segments = _run_diarization_pyannote(wav_path, max_speakers)
            ratios = []
            backend_info = {"backend": "pyannote", "model": DIAR_MODEL}
        else:
            raise HTTPException(503, detail=f"Unsupported backend: {DIAR_BACKEND}")

        out = {
            "segments": segments,
            "info": {
                **backend_info,
                "duration_ms": dur_ms,
                "collar_s": DIAR_COLLAR_SEC,
                "min_speech_s": DIAR_MIN_SPEECH_SEC,
            },
            "speech_ratios": ratios,
            "debug": {"workdir": os.path.basename(workdir), "input_filename": file.filename},
        }
        return JSONResponse(out)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("diarize failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass


# ----------------- ASYNC + JOBS (optional) -----------------
@router.post("/async")
def diarize_async(body: DiarizeAsyncIn, bg: BackgroundTasks):
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
    bg.add_task(_do_diarize_job, jid)
    return {"job_id": jid, "status": "queued"}


@router.get("/jobs/{job_id}")
def diarize_job_status(job_id: str):
    return _job_load(job_id)


def _post_callback(url: str, payload: dict) -> None:
    try:
        import requests
        requests.post(str(url), json=payload, timeout=15)
    except Exception:
        logger.warning("callback post failed", exc_info=True)


def _do_diarize_job(job_id: str) -> None:
    try:
        j = _job_load(job_id)
        req = j.get("request") or {}
        src = _download_to_tmp(req["file_url"])
        workdir = tempfile.mkdtemp(prefix="diar_")
        wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")

        _ffmpeg_wav_mono16k(src, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        if DIAR_BACKEND == "vad":
            segments = _run_diarization_vad(wav_path)
            ratios = []
            backend_info = {"backend": "silero-vad"}
        elif DIAR_BACKEND == "pyannote":
            segments = _run_diarization_pyannote(wav_path, req.get("max_speakers"))
            ratios = []
            backend_info = {"backend": "pyannote", "model": DIAR_MODEL}
        else:
            raise RuntimeError(f"Unsupported backend {DIAR_BACKEND}")

        result = {
            "segments": segments,
            "info": {
                **backend_info,
                "duration_ms": dur_ms,
                "collar_s": DIAR_COLLAR_SEC,
                "min_speech_s": DIAR_MIN_SPEECH_SEC,
            },
            "speech_ratios": ratios,
            "debug": {"source_url": req.get("file_url"), "workdir": os.path.basename(workdir)},
            "meta": req.get("meta") or {},
        }
        j.update({"status": "done", "result": result, "updated_at": int(__import__("time").time())})
        _job_save(j)

        if req.get("callback_url"):
            _post_callback(
                req["callback_url"],
                {"job_id": j["id"], "status": "done", "result": result},
            )

        try:
            shutil.rmtree(os.path.dirname(src), ignore_errors=True)
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
    except Exception as e:
        logger.exception("identify job failed")
        try:
            j = _job_load(job_id)
            j.update(
                {"status": "error", "error": str(e), "updated_at": int(__import__("time").time())}
            )
            _job_save(j)
            req = j.get("request") or {}
            if req.get("callback_url"):
                _post_callback(
                    req["callback_url"],
                    {"job_id": j["id"], "status": "error", "error": str(e)},
                )
        except Exception:
            pass


# ----------------- ENV Debug -----------------
@router.get("/env")
def show_env():
    keys = ["DIAR_BACKEND", "DIAR_MODEL", "DIAR_COLLAR_SEC", "DIAR_MIN_SPEECH_SEC", "FFMPEG_BIN"]
    out = {k: os.getenv(k) for k in keys}
    out["DIAR_AUTH_TOKEN_set"] = bool(DIAR_AUTH_TOKEN)
    return out
