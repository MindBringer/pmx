# app/speakers.py
# FastAPI Router: Speaker Enrollment & CRUD (Qdrant)
# - Uploads ODER file_url(s) werden akzeptiert
# - aus mehreren Audios werden zeitliche Fenster-Embeddings gemittelt (robust)
# - Qdrant Collection "speakers": ein Punkt pro Sprecher
# - Sync + Async + Jobs + ENV-Dump
# - kompatibel mit identify.py (gleiche Embedding-Pipeline)

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
router = APIRouter(prefix="/speakers", tags=["audio", "speakers"])

# ----------------- ENV / Defaults -----------------
FFMPEG_BIN               = os.getenv("FFMPEG_BIN", "ffmpeg")
SPEAKER_BACKEND          = os.getenv("SPEAKER_BACKEND", "pyannote").lower()
SPEAKER_EMBED_MODEL      = os.getenv("SPEAKER_EMBED_MODEL", "pyannote/embedding")
DIAR_AUTH_TOKEN          = os.getenv("DIAR_AUTH_TOKEN", "").strip()

# Qdrant
QDRANT_URL               = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY           = os.getenv("QDRANT_API_KEY", "")
SPEAKER_COLLECTION       = os.getenv("SPEAKER_COLLECTION", "speakers")

# Jobs
JOBS_DIR                 = os.getenv("JOBS_DIR", "/data/jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

# Embedding Fenster-Parameter (robust bei variabler Länge/Qualität)
WIN_SEC                  = float(os.getenv("SPEAKER_WIN_SEC", "1.5"))    # Fensterlänge in Sekunden
HOP_SEC                  = float(os.getenv("SPEAKER_HOP_SEC", "0.75"))   # Schrittweite
MIN_TOTAL_SEC            = float(os.getenv("SPEAKER_MIN_TOTAL_SEC", "1.0"))  # Mindestlänge je Sample

# ----------------- Helpers -----------------
def _ffmpeg_wav_mono16k(inp_path: str, out_path: str) -> None:
    cmd = [FFMPEG_BIN, "-y", "-i", inp_path, "-ac", "1", "-ar", "16000", "-vn", out_path]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed: {proc.stderr.decode(errors='ignore') or proc.stdout.decode(errors='ignore')}"
        )

def _download_to_tmp(url: str, prefix: str = "spk_") -> str:
    import requests
    tmpdir = tempfile.mkdtemp(prefix=prefix)
    dst = os.path.join(tmpdir, "input.bin")
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dst

def _job_path(jid: str) -> str:
    return os.path.join(JOBS_DIR, f"{jid}.spk.json")

def _job_save(j: Dict[str, Any]) -> None:
    with open(_job_path(j["id"]), "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False)

def _job_load(jid: str) -> Dict[str, Any]:
    p = _job_path(jid)
    if not os.path.exists(p):
        raise HTTPException(404, "job not found")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

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

def _embed_slice(wav_path: str, start_ms: int, end_ms: int) -> np.ndarray:
    infer = _load_pyannote_inference()
    s = max(0.0, float(start_ms) / 1000.0)
    e = max(s + 0.1, float(end_ms) / 1000.0)
    vec = infer({"audio": wav_path, "start": s, "end": e})
    return np.asarray(vec, dtype=np.float32)

def _embed_whole_file(wav_path: str, sr_target: int = 16000) -> np.ndarray:
    """Zerlegt die Datei in überlappende Fenster und mittelt die Embeddings."""
    data, sr = sf.read(wav_path, always_2d=False)
    if isinstance(data, np.ndarray):
        if data.ndim > 1:
            data = data[:, 0]
    else:
        data = np.asarray(data)
    n = data.shape[0]
    if n == 0:
        raise HTTPException(400, detail="empty audio")
    dur_s = n / float(sr)
    # zu kurze Dateien: ein Segment komplett
    if dur_s < MIN_TOTAL_SEC:
        return _embed_slice(wav_path, 0, int(dur_s * 1000))

    win = max(0.3, WIN_SEC)
    hop = max(0.1, HOP_SEC)
    pos = 0.0
    vecs: List[np.ndarray] = []
    while pos < max(0.0, dur_s - 0.05):
        start_ms = int(pos * 1000.0)
        end_ms = int(min(dur_s, pos + win) * 1000.0)
        try:
            v = _embed_slice(wav_path, start_ms, end_ms)
            if v is not None and np.linalg.norm(v) > 0:
                vecs.append(v.astype(np.float32))
        except Exception:
            logger.debug("embed slice failed at %.2fs", pos, exc_info=True)
        pos += hop

    if not vecs:
        # Fallback: full file once
        return _embed_slice(wav_path, 0, int(dur_s * 1000))
    M = np.vstack(vecs)  # [num, dim]
    v = M.mean(axis=0)
    # optional L2-Normalisierung
    norm = np.linalg.norm(v)
    if norm > 0:
        v = v / norm
    return v.astype(np.float32)

# ----------------- Qdrant helpers -----------------
def _qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY or None, timeout=30)

def _ensure_collection(dim: int) -> None:
    from qdrant_client.http import models as qmodels
    cli = _qdrant_client()
    try:
        cli.get_collection(SPEAKER_COLLECTION)
        return
    except Exception:
        pass
    cli.recreate_collection(
        collection_name=SPEAKER_COLLECTION,
        vectors_config=qmodels.VectorParams(size=dim, distance=qmodels.Distance.COSINE),
        on_disk=True
    )

def _upsert_speaker(spk_id: str, name: str, tags: List[str], vector: np.ndarray, sources: List[dict], merge: bool = True) -> dict:
    """Upsert einen Sprecherpunkt. Bei merge=True werden vorhandene payload-Felder gemergt und sample_count erhöht."""
    from qdrant_client.http import models as qmodels
    cli = _qdrant_client()
    # ensure collection (dim aus vector)
    _ensure_collection(int(vector.shape[0]))

    # Lesen existierenden Punkt (falls vorhanden)
    existing_payload = None
    try:
        rec = cli.retrieve(SPEAKER_COLLECTION, ids=[spk_id], with_payload=True, with_vectors=False)
        if rec:
            existing_payload = rec[0].payload or {}
    except Exception:
        existing_payload = None

    now = int(time.time())
    if merge and existing_payload:
        # merge name, tags, sources, counters
        name = name or existing_payload.get("name") or spk_id
        prev_tags = existing_payload.get("tags") or []
        tags = list({*prev_tags, *(tags or [])})
        prev_sources = existing_payload.get("sources") or []
        sources = prev_sources + (sources or [])
        sample_count = int(existing_payload.get("sample_count") or 0) + max(1, len(sources))
        payload = {
            **existing_payload,
            "spk_id": spk_id,
            "name": name,
            "tags": tags,
            "sources": sources,
            "sample_count": sample_count,
            "updated_at": now
        }
    else:
        payload = {
            "spk_id": spk_id,
            "name": name or spk_id,
            "tags": tags or [],
            "sources": sources or [],
            "sample_count": max(1, len(sources or [])),
            "created_at": existing_payload.get("created_at") if existing_payload else now,
            "updated_at": now
        }

    cli.upsert(
        collection_name=SPEAKER_COLLECTION,
        points=[{
            "id": spk_id,
            "vector": vector.tolist(),
            "payload": payload
        }]
    )
    return payload

# ----------------- Models -----------------
class EnrollBody(BaseModel):
    name: Optional[str] = None
    tags: Optional[List[str]] = None
    spk_id: Optional[str] = None
    file_urls: Optional[List[AnyHttpUrl]] = None  # alternative zu Uploads
    merge: Optional[bool] = True
    meta: Optional[dict] = None

class SpeakerOut(BaseModel):
    spk_id: str
    name: str
    tags: List[str] = []
    sample_count: int = 0
    sources: List[dict] = []
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

class SpeakersListOut(BaseModel):
    items: List[SpeakerOut]

class UpdateBody(BaseModel):
    name: Optional[str] = None
    tags: Optional[List[str]] = None

class EnrollAsyncIn(EnrollBody):
    callback_url: Optional[AnyHttpUrl] = None

# ----------------- CRUD -----------------
@router.get("", response_model=SpeakersListOut)
def list_speakers():
    from qdrant_client.http import models as qmodels
    cli = _qdrant_client()
    items: List[SpeakerOut] = []
    next_page = None
    while True:
        res = cli.scroll(
            collection_name=SPEAKER_COLLECTION,
            with_vectors=False,
            with_payload=True,
            limit=256,
            offset=next_page
        )
        batch_points, next_page = res[0], res[1]
        for p in batch_points:
            pl = p.payload or {}
            items.append(SpeakerOut(
                spk_id=pl.get("spk_id") or str(p.id),
                name=pl.get("name") or str(p.id),
                tags=pl.get("tags") or [],
                sample_count=int(pl.get("sample_count") or 0),
                sources=pl.get("sources") or [],
                created_at=pl.get("created_at"),
                updated_at=pl.get("updated_at")
            ))
        if next_page is None:
            break
    return {"items": items}

@router.get("/{spk_id}", response_model=SpeakerOut)
def get_speaker(spk_id: str):
    cli = _qdrant_client()
    rec = cli.retrieve(SPEAKER_COLLECTION, ids=[spk_id], with_payload=True, with_vectors=False)
    if not rec:
        raise HTTPException(404, "speaker not found")
    pl = rec[0].payload or {}
    return SpeakerOut(
        spk_id=pl.get("spk_id") or spk_id,
        name=pl.get("name") or spk_id,
        tags=pl.get("tags") or [],
        sample_count=int(pl.get("sample_count") or 0),
        sources=pl.get("sources") or [],
        created_at=pl.get("created_at"),
        updated_at=pl.get("updated_at")
    )

@router.put("/{spk_id}", response_model=SpeakerOut)
def update_speaker(spk_id: str, body: UpdateBody):
    cli = _qdrant_client()
    rec = cli.retrieve(SPEAKER_COLLECTION, ids=[spk_id], with_payload=True, with_vectors=True)
    if not rec:
        raise HTTPException(404, "speaker not found")
    pl = rec[0].payload or {}
    name = body.name if (body.name is not None) else pl.get("name")
    tags = body.tags if (body.tags is not None) else (pl.get("tags") or [])
    updated = {
        **pl,
        "spk_id": spk_id,
        "name": name,
        "tags": tags,
        "updated_at": int(time.time())
    }
    cli.upsert(SPEAKER_COLLECTION, points=[{"id": spk_id, "vector": rec[0].vector, "payload": updated}])
    return SpeakerOut(
        spk_id=spk_id, name=name, tags=tags,
        sample_count=int(updated.get("sample_count") or 0),
        sources=updated.get("sources") or [],
        created_at=updated.get("created_at"),
        updated_at=updated.get("updated_at")
    )

@router.delete("/{spk_id}")
def delete_speaker(spk_id: str):
    cli = _qdrant_client()
    cli.delete(SPEAKER_COLLECTION, points_selector={"points": [spk_id]})
    return {"deleted": spk_id}

# ----------------- ENROLL (Sync) -----------------
@router.post("/enroll", response_model=SpeakerOut)
async def enroll_speaker(
    name: Optional[str] = Form(default=None),
    spk_id: Optional[str] = Form(default=None),
    tags_csv: Optional[str] = Form(default=None),
    merge: Optional[bool] = Form(default=True),
    # Uploads (0..N Files)
    files: Optional[List[UploadFile]] = None,
    # Alternative: URLs (als JSON-String-Liste in Form-Feld "file_urls_json")
    file_urls_json: Optional[str] = Form(default=None),
):
    """
    Legt/aktualisiert einen Sprecher in Qdrant an.
    - Entweder mehrere Dateien hochladen (files[])
    - ODER file_urls_json = '["https://…/a.wav","https://…/b.m4a"]'
    - spk_id weglassen → neuer Sprecher; spk_<uuid>
    - spk_id setzen → Re-Enroll/Merge in vorhandenes Profil
    """
    if SPEAKER_BACKEND != "pyannote":
        raise HTTPException(503, detail="Speaker backend disabled or unsupported.")

    tags = [t.strip() for t in (tags_csv or "").split(",") if t and t.strip()]
    if not files and not file_urls_json:
        raise HTTPException(400, detail="provide at least one file (files[]) or file_urls_json")

    # ---- Material einsammeln
    sources_info: List[dict] = []
    wavs: List[str] = []

    try:
        # Uploads
        if files:
            for up in files:
                tmpdir = tempfile.mkdtemp(prefix="spk_")
                src_path = os.path.join(tmpdir, f"src_{uuid.uuid4().hex}")
                with open(src_path, "wb") as f:
                    while True:
                        chunk = await up.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                wav_path = os.path.join(tmpdir, f"conv_{uuid.uuid4().hex}.wav")
                _ffmpeg_wav_mono16k(src_path, wav_path)
                wavs.append(wav_path)
                sources_info.append({"kind": "upload", "filename": up.filename})

        # URLs
        if file_urls_json:
            try:
                urls = json.loads(file_urls_json)
                assert isinstance(urls, list)
            except Exception as e:
                raise HTTPException(400, detail=f"invalid file_urls_json: {e}")
            for u in urls:
                src = _download_to_tmp(str(u), prefix="spkurl_")
                wav_path = os.path.join(os.path.dirname(src), f"conv_{uuid.uuid4().hex}.wav")
                _ffmpeg_wav_mono16k(src, wav_path)
                wavs.append(wav_path)
                sources_info.append({"kind": "url", "url": u})

        if not wavs:
            raise HTTPException(400, detail="no audio material provided")

        # ---- Embeddings mitteln (alle Dateien → Fenster → mean → mean)
        vecs = []
        for w in wavs:
            v = _embed_whole_file(w)
            if v is not None and np.linalg.norm(v) > 0:
                vecs.append(v.astype(np.float32))
        if not vecs:
            raise HTTPException(400, detail="could not extract embeddings from provided audio")

        V = np.vstack(vecs)
        vmean = V.mean(axis=0)
        norm = np.linalg.norm(vmean)
        if norm > 0:
            vmean = (vmean / norm).astype(np.float32)

        # ---- Upsert in Qdrant
        final_spk_id = spk_id or f"spk_{uuid.uuid4().hex}"
        final_name = name or final_spk_id
        payload = _upsert_speaker(final_spk_id, final_name, tags, vmean, sources_info, merge=bool(merge))

        return JSONResponse(SpeakerOut(
            spk_id=payload["spk_id"],
            name=payload["name"],
            tags=payload.get("tags") or [],
            sample_count=int(payload.get("sample_count") or 0),
            sources=payload.get("sources") or [],
            created_at=payload.get("created_at"),
            updated_at=payload.get("updated_at"),
        ).dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("enroll failed")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        # cleanup tmp
        try:
            for w in wavs:
                root = os.path.dirname(w)
                shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass

# ----------------- ENROLL (Async) -----------------
class EnrollAsyncBody(EnrollAsyncIn):
    pass

@router.post("/enroll/async")
def enroll_async(body: EnrollAsyncBody, bg: BackgroundTasks):
    if SPEAKER_BACKEND != "pyannote":
        raise HTTPException(503, detail="Speaker backend disabled or unsupported.")
    if not (body.file_urls and len(body.file_urls) > 0):
        raise HTTPException(400, detail="async enroll requires file_urls[]")

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
    bg.add_task(_do_enroll_job, jid)
    return {"job_id": jid, "status": "queued"}

@router.get("/jobs/{job_id}")
def enroll_job_status(job_id: str):
    return _job_load(job_id)

def _post_callback(url: str, payload: dict) -> None:
    try:
        import requests
        requests.post(str(url), json=payload, timeout=15)
    except Exception:
        logger.warning("callback post failed", exc_info=True)

def _do_enroll_job(job_id: str) -> None:
    try:
        j = _job_load(job_id)
        req = j.get("request") or {}

        wavs: List[str] = []
        sources_info: List[dict] = []
        for u in req.get("file_urls") or []:
            src = _download_to_tmp(str(u), prefix="spkurl_")
            wav_path = os.path.join(os.path.dirname(src), f"conv_{uuid.uuid4().hex}.wav")
            _ffmpeg_wav_mono16k(src, wav_path)
            wavs.append(wav_path)
            sources_info.append({"kind": "url", "url": u})

        if not wavs:
            raise RuntimeError("no audio material provided")

        vecs = []
        for w in wavs:
            v = _embed_whole_file(w)
            if v is not None and np.linalg.norm(v) > 0:
                vecs.append(v.astype(np.float32))
        if not vecs:
            raise RuntimeError("could not extract embeddings from provided audio")

        V = np.vstack(vecs)
        vmean = V.mean(axis=0)
        norm = np.linalg.norm(vmean)
        if norm > 0:
            vmean = (vmean / norm).astype(np.float32)

        final_spk_id = req.get("spk_id") or f"spk_{uuid.uuid4().hex}"
        final_name = req.get("name") or final_spk_id
        tags = req.get("tags") or []
        payload = _upsert_speaker(final_spk_id, final_name, tags, vmean, sources_info, merge=bool(req.get("merge", True)))

        result = {
            "speaker": payload,
            "meta": req.get("meta") or {}
        }
        j.update({"status": "done", "result": result, "updated_at": int(time.time())})
        _job_save(j)

        if req.get("callback_url"):
            _post_callback(req["callback_url"], {"job_id": j["id"], "status": "done", "result": result})

        try:
            # cleanup
            for w in wavs:
                shutil.rmtree(os.path.dirname(w), ignore_errors=True)
        except Exception:
            pass

    except Exception as e:
        logger.exception("enroll job failed")
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
        "SPEAKER_BACKEND", "SPEAKER_EMBED_MODEL",
        "SPEAKER_COLLECTION", "QDRANT_URL",
        "SPEAKER_WIN_SEC", "SPEAKER_HOP_SEC", "SPEAKER_MIN_TOTAL_SEC",
        "FFMPEG_BIN"
    ]
    out = { k: os.getenv(k) for k in keys }
    out["DIAR_AUTH_TOKEN_set"] = bool(DIAR_AUTH_TOKEN)
    out["QDRANT_API_KEY_set"] = bool(QDRANT_API_KEY)
    return out
