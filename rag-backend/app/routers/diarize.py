# app/diarize.py
# FastAPI Router: Diarization (Sync + Async + Jobs + Env)
# Backends:
#   - "vad"       : Silero-VAD (schnell, CPU)
#   - "pyannote"  : pyannote.audio (präzise, langsam)
# Einheitliche Ausgabe: segments[{start_ms, end_ms, spk}]

import os
import io
import uuid
import json
import math
import shutil
import tempfile
import logging
import subprocess
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import soundfile as sf
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, AnyHttpUrl

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/diarize", tags=["audio"])

# ----------------- ENV / Defaults -----------------
FFMPEG_BIN              = os.getenv("FFMPEG_BIN", "ffmpeg")

# Backend-Auswahl: "pyannote" | "vad"
DIAR_BACKEND            = os.getenv("DIAR_BACKEND", "vad").lower()

# Für pyannote (optional):
DIAR_MODEL              = os.getenv("DIAR_MODEL", "pyannote/speaker-diarization-3.1")
DIAR_AUTH_TOKEN         = os.getenv("DIAR_AUTH_TOKEN", "").strip()

# Gemeinsame Feintuning-Parameter (werden für beide Backends genutzt, wo sinnvoll)
DIAR_COLLAR_SEC         = float(os.getenv("DIAR_COLLAR_SEC", "0.05"))
DIAR_MIN_SPEECH_SEC     = float(os.getenv("DIAR_MIN_SPEECH_SEC", "0.2"))

# Jobs
JOBS_DIR                = os.getenv("JOBS_DIR", "/data/jobs")
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

# ----------------- Silero-VAD Backend -----------------
# Wir nutzen torch.hub, CPU-fähig. Keine HF-Token nötig.
_silero_model = None

def _load_silero():
    global _silero_model
    if _silero_model is not None:
        return _silero_model
    import torch
    _silero_model = torch.hub.load(
        repo_or_dir='snakers4/silero-vad',
        model='silero_vad',
        trust_repo=True
    )
    _silero_model.eval()
    logger.info("Loaded Silero-VAD via torch.hub")
    return _silero_model

def _silero_frame_probs(wav_path: str, window_ms: int = 30) -> Tuple[np.ndarray, int]:
    """
    Erzeugt Sprach-/Nichtsprach-Wahrscheinlichkeiten über das Signal.
    window_ms: 10/20/30ms Fenster (Silero nutzt 16000Hz)
    """
    import torch
    model = _load_silero()
    wav, sr = sf.read(wav_path)
    if wav.ndim > 1:
        wav = wav[:,0]
    if sr != 16000:
        raise RuntimeError("expected 16kHz mono WAV after ffmpeg")

    # in Tensor
    audio = torch.tensor(wav, dtype=torch.float32).unsqueeze(0)
    # Silero helper:
    from torch.nn.functional import pad

    # Schrittweite in Samples
    hop = int(sr * (window_ms / 1000.0))
    probs = []
    i = 0
    with torch.no_grad():
        while i < audio.shape[1]:
            j = min(audio.shape[1], i + hop)
            chunk = audio[:, i:j]
            if chunk.shape[1] < hop:
                chunk = pad(chunk, (0, hop - chunk.shape[1]))
            p = model(chunk, 16000).item()
            probs.append(p)
            i = j
    return np.asarray(probs, dtype=np.float32), hop  # hop = samples pro frame

def _probs_to_segments(probs: np.ndarray,
                       hop_samples: int,
                       sr: int = 16000,
                       threshold: float = 0.5,
                       min_speech_s: float = 0.2,
                       min_silence_s: float = 0.5,
                       collar_s: float = 0.05) -> List[Dict[str, int]]:
    """
    Schwellenwert-basiert: erstelle Segmente aus Frame-Probabilitäten.
    """
    frames = (probs >= threshold).astype(np.int32)
    segs = []
    in_speech = False
    start_f = 0
    for f, v in enumerate(frames):
        if v and not in_speech:
            in_speech = True
            start_f = f
        elif (not v) and in_speech:
            in_speech = False
            end_f = f
            segs.append((start_f, end_f))
    if in_speech:
        segs.append((start_f, len(frames)))

    # zu ms
    out = []
    for (fs, fe) in segs:
        start_ms = int((fs * hop_samples) * 1000 / sr)
        end_ms   = int((fe * hop_samples) * 1000 / sr)
        if end_ms <= start_ms:
            continue
        out.append({"start_ms": start_ms, "end_ms": end_ms, "spk": "SPEECH"})

    # zusammenführen enger Grenzen (collar)
    if collar_s > 0 and out:
        merged = [out[0]]
        collar_ms = int(collar_s * 1000)
        for s in out[1:]:
            last = merged[-1]
            if s["start_ms"] - last["end_ms"] <= collar_ms:
                last["end_ms"] = max(last["end_ms"], s["end_ms"])
            else:
                merged.append(s)
        out = merged

    # kurze Schnipsel verwerfen
    if min_speech_s > 0:
        min_ms = int(min_speech_s * 1000)
        out = [s for s in out if (s["end_ms"] - s["start_ms"]) >= min_ms]

    # sehr kurze Pausen ignorieren (re-merge nach Filter)
    if collar_s > 0 and out:
        merged = [out[0]]
        collar_ms = int(collar_s * 1000)
        for s in out[1:]:
            last = merged[-1]
            if s["start_ms"] - last["end_ms"] <= collar_ms:
                last["end_ms"] = max(last["end_ms"], s["end_ms"])
            else:
                merged.append(s)
        out = merged

    return out

def _run_diarization_vad(wav_path: str) -> List[Dict[str, Any]]:
    probs, hop = _silero_frame_probs(wav_path, window_ms=30)
    segments = _probs_to_segments(
        probs,
        hop_samples=hop,
        sr=16000,
        threshold=0.5,
        min_speech_s=DIAR_MIN_SPEECH_SEC,
        min_silence_s=0.5,
        collar_s=DIAR_COLLAR_SEC
    )
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
    speech_ratios: Optional[List[dict]] = None  # im VAD-Backend leer
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
            ratios = []  # Redeanteile nach Identify
            backend_info = {"backend": "silero-vad"}
        elif DIAR_BACKEND == "pyannote":
            segments = _run_diarization_pyannote(wav_path, max_speakers)
            # optional: hier könnten speech_ratios wie zuvor berechnet werden
            ratios = []  # lassen leer; wir rechnen nach Identify sauber
            backend_info = {"backend": "pyannote", "model": DIAR_MODEL}
        else:
            raise HTTPException(503, detail=f"Diarization backend disabled or unsupported: {DIAR_BACKEND}")

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

# ----------------- ASYNC + JOBS (optional beibehalten) -----------------
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
            raise RuntimeError(f"unsupported backend {DIAR_BACKEND}")

        result = {
            "segments": segments,
            "info": { **backend_info, "duration_ms": dur_ms,
                      "collar_s": DIAR_COLLAR_SEC, "min_speech_s": DIAR_MIN_SPEECH_SEC },
            "speech_ratios": ratios,
            "debug": {"source_url": req.get("file_url"), "workdir": os.path.basename(workdir)},
            "meta": req.get("meta") or {},
        }
        j.update({"status": "done", "result": result, "updated_at": int(__import__("time").time())})
        _job_save(j)

        if req.get("callback_url"):
            _post_callback(req["callback_url"], {"job_id": j["id"], "status": "done", "result": result})

        try:
            shutil.rmtree(os.path.dirname(src), ignore_errors=True)
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass
    except Exception as e:
        logger.exception("diarize job failed")
        try:
            j = _job_load(job_id)
            j.update({"status": "error", "error": str(e), "updated_at": int(__import__("time").time())})
            _job_save(j)
            req = j.get("request") or {}
            if req.get("callback_url"):
                _post_callback(req["callback_url"], {"job_id": j["id"], "status": "error", "error": str(e)})
        except Exception:
            pass

# ----------------- ENV Debug -----------------
@router.get("/env")
def show_env():
    keys = [ "DIAR_BACKEND", "DIAR_MODEL", "DIAR_COLLAR_SEC", "DIAR_MIN_SPEECH_SEC", "FFMPEG_BIN" ]
    out = { k: os.getenv(k) for k in keys }
    out["DIAR_AUTH_TOKEN_set"] = bool(DIAR_AUTH_TOKEN)
    return out
