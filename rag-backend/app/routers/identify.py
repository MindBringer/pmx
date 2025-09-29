# app/identify.py
# FastAPI Router: Speaker Identification (Sync + Async + Jobs + Env)
# - Nimmt Audio + optionale Segmente (aus /diarize)
# - Extrahiert Speaker-Embeddings (pyannote) je Segment
# - Matched gegen Qdrant-"speakers"-Collection (oder lokalen Fallback)
# - Gibt pro Segment das beste Match mit Score & Zeitintervall zurück

import os
import io
import uuid
import json
import time
import math
import shutil
import logging
import tempfile
import subprocess
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import soundfile as sf
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, AnyHttpUrl

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/identify", tags=["audio"])

# ----------------- ENV / Defaults -----------------
FFMPEG_BIN               = os.getenv("FFMPEG_BIN", "ffmpeg")

# Embedding backend
SPEAKER_BACKEND          = os.getenv("SPEAKER_BACKEND", "pyannote").lower()
SPEAKER_EMBED_MODEL      = os.getenv("SPEAKER_EMBED_MODEL", "pyannote/embedding")
DIAR_AUTH_TOKEN          = os.getenv("DIAR_AUTH_TOKEN", "").strip()  # HF-Token wird wiederverwendet

# Matching
SPEAKER_THRESHOLD        = float(os.getenv("SPEAKER_THRESHOLD", "0.65"))  # Cosine similarity threshold
TOP_K                    = int(os.getenv("SPEAKER_TOPK", "1"))

# Qdrant
QDRANT_URL               = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY           = os.getenv("QDRANT_API_KEY", "")
SPEAKER_COLLECTION       = os.getenv("SPEAKER_COLLECTION", "speakers")

# Jobs
JOBS_DIR                 = os.getenv("JOBS_DIR", "/data/jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

# Fallback local DB
LOCAL_SPEAKERS_JSON      = os.getenv("LOCAL_SPEAKERS_JSON", "/data/speakers.json")

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
    return os.path.join(JOBS_DIR, f"{jid}.ident.json")

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
    tmpdir = tempfile.mkdtemp(prefix="ident_")
    dst = os.path.join(tmpdir, "input.bin")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dst

# Cosine similarity
def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    da = np.linalg.norm(a)
    db = np.linalg.norm(b)
    if da == 0.0 or db == 0.0:
        return 0.0
    return float(np.dot(a, b) / (da * db))

# ----------------- Embedding backend (lazy) -----------------
_pyannote_infer = None

def _load_pyannote_inference():
    global _pyannote_infer
    if _pyannote_infer is not None:
        return _pyannote_infer
    if SPEAKER_BACKEND != "pyannote":
        raise HTTPException(503, detail="Speaker backend is disabled (SPEAKER_BACKEND != 'pyannote').")
    try:
        from pyannote.audio import Inference
    except Exception as e:
        raise HTTPException(503, detail=f"pyannote.audio not available: {e}")
    if not DIAR_AUTH_TOKEN:
        raise HTTPException(503, detail="DIAR_AUTH_TOKEN missing for pyannote embedding backend.")
    _pyannote_infer = Inference(SPEAKER_EMBED_MODEL, use_auth_token=DIAR_AUTH_TOKEN)
    logger.info("Loaded pyannote embedding model=%s", SPEAKER_EMBED_MODEL)
    return _pyannote_infer

def _embed_segment(wav_path: str, start_ms: int, end_ms: int) -> np.ndarray:
    """Compute embedding for a time slice [start_ms, end_ms) of wav_path."""
    infer = _load_pyannote_inference()
    start_s = max(0.0, float(start_ms) / 1000.0)
    end_s = max(start_s + 0.1, float(end_ms) / 1000.0)  # avoid zero-length
    # pyannote Inference can take {"start":..., "end":...}
    emb = infer({"audio": wav_path, "start": start_s, "end": end_s})
    # emb is np.ndarray shape (dim,)
    return np.asarray(emb, dtype=np.float32)

# ----------------- Speakers DB (Qdrant + fallback) -----------------
def _load_speakers_from_qdrant() -> List[Dict[str, Any]]:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qmodels

    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None, timeout=30)
    # Scroll all points from collection
    points: List[Dict[str, Any]] = []
    next_page = None
    while True:
        res = client.scroll(
            collection_name=SPEAKER_COLLECTION,
            with_vectors=True,
            with_payload=True,
            limit=256,
            offset=next_page
        )
        batch_points, next_page = res[0], res[1]
        for p in batch_points:
            payload = p.payload or {}
            vec = p.vector
            if vec is None:
                continue
            # expected payload: { "spk_id": "...", "name": "...", "tags": [...] }
            points.append({
                "spk_id": payload.get("spk_id") or str(p.id),
                "name": payload.get("name") or str(p.id),
                "vector": np.asarray(vec, dtype=np.float32),
                "payload": payload
            })
        if next_page is None:
            break
    return points

def _load_speakers_fallback() -> List[Dict[str, Any]]:
    if not os.path.exists(LOCAL_SPEAKERS_JSON):
        return []
    try:
        with open(LOCAL_SPEAKERS_JSON, "r", encoding="utf-8") as f:
            items = json.load(f)
        out = []
        for it in items:
            if "vector" not in it:
                continue
            out.append({
                "spk_id": it.get("spk_id") or it.get("id") or uuid.uuid4().hex,
                "name": it.get("name") or it.get("label") or it.get("spk_id"),
                "vector": np.asarray(it["vector"], dtype=np.float32),
                "payload": it
            })
        return out
    except Exception:
        logger.exception("failed to load local speakers json")
        return []

def _load_enrolled_speakers() -> List[Dict[str, Any]]:
    # Prefer Qdrant; fallback to local json file
    try:
        spk = _load_speakers_from_qdrant()
        if spk:
            return spk
    except Exception:
        logger.warning("Qdrant speaker load failed, falling back to local JSON", exc_info=True)
    return _load_speakers_fallback()

# ----------------- Models -----------------
class SegmentIn(BaseModel):
    start_ms: int
    end_ms: int
    spk: Optional[str] = None

class IdentifyOut(BaseModel):
    matches: List[dict]
    info: dict
    debug: Optional[dict] = None

class IdentifyAsyncIn(BaseModel):
    file_url: AnyHttpUrl
    segments: Optional[List[SegmentIn]] = None
    threshold: Optional[float] = None
    top_k: Optional[int] = None
    callback_url: Optional[AnyHttpUrl] = None
    meta: Optional[dict] = None

# ----------------- Core matching -----------------
def _match_embeddings(emb: np.ndarray, enrolled: List[Dict[str, Any]], top_k: int = 1) -> List[Tuple[str, str, float]]:
    """Return top_k matches as (spk_id, name, score)."""
    scores = []
    for e in enrolled:
        s = _cosine(emb, e["vector"])
        scores.append((e["spk_id"], e["name"], s))
    scores.sort(key=lambda t: t[2], reverse=True)
    return scores[:max(1, top_k)]

def _identify_segments(wav_path: str, segments: List[SegmentIn], thr: float, top_k: int) -> Tuple[List[dict], dict]:
    enrolled = _load_enrolled_speakers()
    if not enrolled:
        raise HTTPException(503, detail="No enrolled speakers found (Qdrant empty and no local fallback).")

    matches: List[dict] = []
    processed = 0
    for seg in segments:
        processed += 1
        emb = _embed_segment(wav_path, seg.start_ms, seg.end_ms)
        tops = _match_embeddings(emb, enrolled, top_k=top_k)
        if not tops:
            continue
        best_id, best_name, best_score = tops[0]
        if best_score >= thr:
            matches.append({
                "from_ms": int(seg.start_ms),
                "to_ms": int(seg.end_ms),
                "spk": seg.spk,          # diarization label if provided
                "spk_id": best_id,
                "name": best_name,
                "score": round(float(best_score), 4),
                "alts": [
                    {"spk_id": sid, "name": nm, "score": round(float(sc), 4)}
                    for (sid, nm, sc) in tops
                ]
            })
        else:
            # Optional: emit 'unknown' with best candidate
            matches.append({
                "from_ms": int(seg.start_ms),
                "to_ms": int(seg.end_ms),
                "spk": seg.spk,
                "spk_id": None,
                "name": "unknown",
                "score": round(float(best_score), 4),
                "alts": [
                    {"spk_id": sid, "name": nm, "score": round(float(sc), 4)}
                    for (sid, nm, sc) in tops
                ]
            })
    info = {
        "enrolled_count": len(enrolled),
        "segments_processed": processed,
        "threshold": thr,
        "top_k": top_k,
        "backend": SPEAKER_BACKEND,
        "embed_model": SPEAKER_EMBED_MODEL,
    }
    return matches, info

# ----------------- SYNC -----------------
@router.post("", response_model=IdentifyOut)
async def identify_endpoint(
    file: UploadFile = File(...),
    segments_json: Optional[str] = Form(default=None),   # JSON-Array [{start_ms,end_ms,spk?}]
    threshold: Optional[float] = Form(default=None),
    top_k: Optional[int] = Form(default=None),
):
    """
    Speaker-Identifikation (synchron).
    Erwartet Segmente (z. B. aus /diarize). Ohne Segmente wird die gesamte Datei als ein Segment behandelt.
    """
    if SPEAKER_BACKEND != "pyannote":
        raise HTTPException(503, detail="Speaker backend disabled or unsupported.")
    workdir = tempfile.mkdtemp(prefix="ident_")
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

        segs: List[SegmentIn] = []
        if segments_json:
            try:
                raw = json.loads(segments_json)
                for r in raw:
                    segs.append(SegmentIn(**r))
            except Exception as e:
                raise HTTPException(400, detail=f"invalid segments_json: {e}")
        if not segs:
            # fallback: one segment = full audio
            segs = [SegmentIn(start_ms=0, end_ms=dur_ms, spk=None)]

        thr = float(threshold) if (threshold is not None) else SPEAKER_THRESHOLD
        tk = int(top_k) if (top_k is not None) else TOP_K

        matches, info = _identify_segments(wav_path, segs, thr, tk)
        out = {
            "matches": matches,
            "info": { **info, "duration_ms": dur_ms },
            "debug": { "input_filename": file.filename, "workdir": os.path.basename(workdir) }
        }
        return JSONResponse(out)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("identify failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

# ----------------- ASYNC + JOBS -----------------
class IdentifyAsyncBody(IdentifyAsyncIn):
    pass

@router.post("/async")
def identify_async(body: IdentifyAsyncBody, bg: BackgroundTasks):
    if SPEAKER_BACKEND != "pyannote":
        raise HTTPException(503, detail="Speaker backend disabled or unsupported.")
    jid = uuid.uuid4().hex
    job = {
        "id": jid,
        "status": "queued",
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "request": body.dict(),
        "result": None,
        "error": None,
    }
    _job_save(job)
    bg.add_task(_do_identify_job, jid)
    return {"job_id": jid, "status": "queued"}

@router.get("/jobs/{job_id}")
def identify_job_status(job_id: str):
    return _job_load(job_id)

def _post_callback(url: str, payload: dict) -> None:
    try:
        import requests
        requests.post(str(url), json=payload, timeout=15)
    except Exception:
        logger.warning("callback post failed", exc_info=True)

def _do_identify_job(job_id: str) -> None:
    try:
        j = _job_load(job_id)
        req = j.get("request") or {}
        src = _download_to_tmp(req["file_url"])
        workdir = tempfile.mkdtemp(prefix="ident_")
        wav_path = os.path.join(workdir, f"conv_{uuid.uuid4().hex}.wav")

        _ffmpeg_wav_mono16k(src, wav_path)
        dur_ms = _audio_duration_ms(wav_path)

        segs: List[SegmentIn] = []
        raw_segments = req.get("segments")
        if raw_segments:
            for r in raw_segments:
                segs.append(SegmentIn(**r))
        if not segs:
            segs = [SegmentIn(start_ms=0, end_ms=dur_ms, spk=None)]

        thr = float(req.get("threshold") or SPEAKER_THRESHOLD)
        tk = int(req.get("top_k") or TOP_K)

        matches, info = _identify_segments(wav_path, segs, thr, tk)
        result = {
            "matches": matches,
            "info": { **info, "duration_ms": dur_ms },
            "debug": { "source_url": req.get("file_url"), "workdir": os.path.basename(workdir) },
            "meta": req.get("meta") or {}
        }

        j.update({"status": "done", "result": result, "updated_at": int(time.time())})
        _job_save(j)

        if req.get("callback_url"):
            _post_callback(req["callback_url"], {"job_id": j["id"], "status": "done", "result": result})

        try:
            shutil.rmtree(os.path.dirname(src), ignore_errors=True)
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass

    except Exception as e:
        logger.exception("identify job failed")
        try:
            j = _job_load(job_id)
            j.update({"status": "error", "error": str(e), "updated_at": int(time.time())})
            _job_save(j)
            req = j.get("request") or {}
            if req.get("callback_url"):
                _post_callback(req["callback_url"], {"job_id": j["id"], "status": "error", "error": str(e)})
        except Exception:
            pass

# ----------------- ENV Debug -----------------
@router.get("/env")
def show_env():
    keys = [
        "SPEAKER_BACKEND", "SPEAKER_EMBED_MODEL", "SPEAKER_THRESHOLD", "SPEAKER_TOPK",
        "SPEAKER_COLLECTION", "QDRANT_URL"
    ]
    out = { k: os.getenv(k) for k in keys }
    out["DIAR_AUTH_TOKEN_set"] = bool(DIAR_AUTH_TOKEN)
    out["QDRANT_API_KEY_set"] = bool(QDRANT_API_KEY)
    return out
