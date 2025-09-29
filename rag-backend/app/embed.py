# app/embed.py
# FastAPI Router: /embed
# - POST /embed            -> {vectors:[...], dim:int, model:str}
# - GET  /embed/env        -> aktuelle ENV/Status
# - Lazy-Load SentenceTransformer, batching, optional normalize
# - Override pro Request: model, normalize, batch_size

import os
import math
import logging
from typing import List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/embed", tags=["embeddings"])

# -------- ENV / Defaults --------
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DEVICE = os.getenv("EMBED_DEVICE", "cpu")  # "cpu" | "cuda"
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "32"))
EMBED_NORMALIZE = os.getenv("EMBED_NORMALIZE", "true").lower() in ("1", "true", "yes", "on")
EMBED_TRUST_REMOTE = os.getenv("EMBED_TRUST_REMOTE", "false").lower() in ("1","true","yes","on")

# Lazy global
_st_model = None
_st_name = None

def _get_model(name: Optional[str] = None):
    global _st_model, _st_name
    req = name or EMBED_MODEL
    if _st_model is not None and _st_name == req:
        return _st_model, _st_name
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        raise HTTPException(503, detail=f"sentence-transformers not available: {e}")
    logger.info("Loading embedding model: %s on %s", req, EMBED_DEVICE)
    _st_model = SentenceTransformer(req, device=EMBED_DEVICE, trust_remote_code=EMBED_TRUST_REMOTE)
    _st_name = req
    return _st_model, _st_name

def _to_lists(arr: np.ndarray) -> List[List[float]]:
    return [row.astype(np.float32).tolist() for row in np.asarray(arr)]

class EmbedIn(BaseModel):
    texts: List[str]
    model: Optional[str] = None
    normalize: Optional[bool] = None
    batch_size: Optional[int] = None

class EmbedOut(BaseModel):
    vectors: List[List[float]]
    dim: int
    model: str

@router.post("", response_model=EmbedOut)
def embed(body: EmbedIn):
    if not body.texts or not isinstance(body.texts, list):
        raise HTTPException(400, detail="texts must be a non-empty list")
    model, name = _get_model(body.model)
    normalize = EMBED_NORMALIZE if (body.normalize is None) else bool(body.normalize)
    batch = EMBED_BATCH if (body.batch_size is None or body.batch_size <= 0) else int(body.batch_size)

    # encode in batches to protect memory
    vecs = []
    N = len(body.texts)
    for i in range(0, N, batch):
        part = body.texts[i:i+batch]
        embs = model.encode(part, normalize_embeddings=normalize, convert_to_numpy=True, show_progress_bar=False)
        vecs.append(embs)
    V = np.vstack(vecs)
    if V.size == 0:
        return {"vectors": [], "dim": 0, "model": name}
    return {"vectors": _to_lists(V), "dim": int(V.shape[1]), "model": name}

@router.get("/env")
def embed_env():
    try:
        _, name = _get_model()
        loaded = True
    except HTTPException:
        loaded = False
        name = EMBED_MODEL
    return {
        "EMBED_MODEL": EMBED_MODEL,
        "EMBED_DEVICE": EMBED_DEVICE,
        "EMBED_BATCH": EMBED_BATCH,
        "EMBED_NORMALIZE": EMBED_NORMALIZE,
        "EMBED_TRUST_REMOTE": EMBED_TRUST_REMOTE,
        "loaded_model": name,
        "loaded": loaded
    }
