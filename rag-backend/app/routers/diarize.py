# app/diarize.py
# FastAPI Router: Diarization (Sync + Async + Jobs + Env)
# - Einheitliche Ausgabe: segments[{start_ms, end_ms, spk}]
# - Backend: pyannote (optional), sauber gekapselt
# - Async-Jobs mit file_url + optionalem callback_url
# - Speech-Ratios (Redeanteile) werden mitgeliefert

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

# Backend-Auswahl: "pyannote" | "none"
DIAR_BACKEND            = os.getenv("DIAR_BACKEND", "pyannote").lower()

# Für pyannote:
DIAR_MODEL              = os.getenv("DIAR_MODEL", "pyannote/speaker-diarization-3.1")
DIAR_AUTH_TOKEN         = os.getenv("DIAR_AUTH_TOKEN", "").strip()  # HF-Token benötigt
# Optional: feste Sprecherzahl (sonst auto)
DIAR_MAX_SPEAKERS_ENV   = os.getenv("DIAR_MAX_SPEAKERS", "")
DIAR_MAX_SPEAKERS       = int(DIAR_MAX_SPEAKERS_ENV) if DIAR_MAX_SPEAKERS_ENV.isdigit() else None

# Feintuning
DIAR_COLLAR_SEC         = float(os.getenv("DIAR_COLLAR_SEC", "0.05"))     # Zusammenführen nahe Grenzen
DIAR_MIN_SPEECH_SEC     = float(os.getenv("DIAR_MIN_SPEECH_SEC", "0.2"))  # kurze Schnipsel verwerfen/mergen

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

# ----------------- Pyannote Pipeline (lazy) -----------------
_pyannote = None

def _load_pyannote():
    global _pyannote
    if _pyannote is not None:
        return _pyannote
    if DIAR_BACKEND != "pyannote":
        raise HTTPException(503, detail="Diarization backend is disabled (DIAR_BACKEND != 'pyannote').")
    try:
        from pyannote.audio import Pipeline
    except Exception as e:
        raise HTTPException(503, detail=f"pyannote.audio not available: {e}")
    if not DIAR_AUTH_TOKEN:
        raise HTTPException(503, detail="DIAR_AUTH_TOKEN missing for pyannote backend.")
    _pyannote = Pipeline.from_pretrained(DIAR_MODEL, use_auth_token=DIAR_AUTH_TOKEN)
    logger.info("Loaded pyannote pipeline model=%s", DIAR_MODEL)
    return _pyannote

# ----------------- Core diarization -----------------
def _merge_close_segments(segments: List[Dict[str, Any]], collar_s: float) -> List[Dict[str, Any]]:
    """Fasst benachbarte Segmente gleicher Sprecher zusammen, wenn sie nahe beieinander liegen."""
    if not segments:
        return []
    out = [segments[0]]
    for seg in segments[1:]:
        last = out[-1]
        if seg["spk"] == last["spk"] and (seg["start_ms"] - last["end_ms"]) <= int(collar_s * 1000):
            last["end_ms"] = max(last["end_ms"], seg["end_ms"])
        else:
            out.append(seg)
    return out

def _drop_tiny_segments(segments: List[Dict[str, Any]], min_len_s: float) -> List[Dict[str, Any]]:
    if min_len_s <= 0:
        return segments
    min_ms = int(min_len_s * 1000)
    return [s for s in segments if (s["end_ms"] - s["start_ms"]) >= min_ms]

def _speech_ratios(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Summiert Redezeit pro Sprecher."""
    agg: Dict[str, int] = {}
    for s in segments:
        dur = max(0, s["end_ms"] - s["start_ms"])
        agg[s["spk"]] = agg.get(s["spk"], 0) + dur
    total = sum(agg.values()) or 1
    out = []
    for spk, ms in sorted(agg.items(), key=lambda kv: -kv[1]):
        out.append({"name": spk, "sekunden": int(ms / 1000), "anteil_prozent": round(100.0 * ms / total, 2)})
    return out

def _run_diarization_pyannote(wav_path: str, max_speakers: Optional[int]) -> List[Dict[str, Any]]:
    pipeline = _load_pyannote()
    diar = pipeline(wav_path, num_speakers=max_speakers) if max_speakers else pipeline(wav_path)
    # Ergebnis in {start_ms,end_ms,spk} transformieren
    segments: List[Dict[str, Any]] = []
    # pyannote liefert speaker labels z.B. SPEAKER_00, SPEAKER_01 ...
    speaker_map: Dict[str, str] = {}

    for turn, _, speaker in diar.itertracks(yield_label=True):
        spk_label = speaker_map.setdefault(speaker, f"S{len(speaker_map)+1}")
        start_ms = int(1000 * float(turn.start))
        end_ms = int(1000 * float(turn.end))
        if end_ms <= start_ms:
            continue
        segments.append({"start_ms": start_ms, "end_ms": end_ms, "spk": spk_label})

    # sortieren & Aufräumen
    segments.sort(key=lambda s: (s["start_ms"], s["end_ms"]))
    segments = _merge_close_segments(segments, DIAR_COLLAR_SEC)
    segments = _drop_tiny_segments(segments, DIAR_MIN_SPEECH_SEC)
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
    """
    Diarization synchron aus Datei-Upload.
    """
    if DIAR_BACKEND != "pyannote":
        raise HTTPException(503, detail="Diarization backend disabled or unsupported.")
    workdir = tempfile.mkdtemp(prefix="diar_")
    src_path = os.path.join(workdir, f"src_{uuid.uuid4().hex}")
    wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")
    try:
        # persist upload
        with open(src_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        _ffmpeg_wav_mono16k(src_path, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        segments = _run_diarization_pyannote(wav_path, max_speakers or DIAR_MAX_SPEAKERS)
        ratios = _speech_ratios(segments)

        out = {
            "segments": segments,
            "info": {
                "backend": "pyannote",
                "model": DIAR_MODEL,
                "duration_ms": dur_ms,
                "max_speakers": max_speakers or DIAR_MAX_SPEAKERS,
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

# ----------------- ASYNC + JOBS -----------------
@router.post("/async")
def diarize_async(body: DiarizeAsyncIn, bg: BackgroundTasks):
    if DIAR_BACKEND != "pyannote":
        raise HTTPException(503, detail="Diarization backend disabled or unsupported.")
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

        segments = _run_diarization_pyannote(wav_path, req.get("max_speakers") or DIAR_MAX_SPEAKERS)
        ratios = _speech_ratios(segments)

        result = {
            "segments": segments,
            "info": {
                "backend": "pyannote",
                "model": DIAR_MODEL,
                "duration_ms": dur_ms,
                "max_speakers": req.get("max_speakers") or DIAR_MAX_SPEAKERS,
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
    keys = [ "DIAR_BACKEND", "DIAR_MODEL", "DIAR_MAX_SPEAKERS", "DIAR_COLLAR_SEC", "DIAR_MIN_SPEECH_SEC", "FFMPEG_BIN" ]
    out = { k: os.getenv(k) for k in keys }
    out["DIAR_AUTH_TOKEN_set"] = bool(DIAR_AUTH_TOKEN)
    return out
