# app/qdrant_api.py
# FastAPI Router: /qdrant
# - POST /qdrant/upsert      -> upsert points (auto-create collection)
# - GET  /qdrant/collections -> list collections (name, vectors_count, config)
# - GET  /qdrant/health      -> basic ping

import os
import logging
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/qdrant", tags=["qdrant"])

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "") or None
QDRANT_DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")
QDRANT_ON_DISK = os.getenv("QDRANT_ON_DISK", "true").lower() in ("1","true","yes","on")
QDRANT_DISTANCE = os.getenv("QDRANT_DISTANCE", "COSINE").upper()  # COSINE | DOT | EUCLID

def _client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, timeout=30)

def _ensure_collection(name: str, dim: int):
    from qdrant_client.http import models as qm
    cli = _client()
    try:
        cli.get_collection(name)
        return
    except Exception:
        pass
    dist = getattr(qm.Distance, QDRANT_DISTANCE, qm.Distance.COSINE)
    cli.recreate_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(size=int(dim), distance=dist),
        on_disk=QDRANT_ON_DISK
    )

class Point(BaseModel):
    id: Any
    vector: List[float] = Field(..., description="Embedding vector")
    payload: Dict[str, Any] = Field(default_factory=dict)

class UpsertIn(BaseModel):
    points: List[Point]
    collection: Optional[str] = None
    # optional consistency & ordering
    wait: Optional[bool] = False

@router.post("/upsert")
def upsert_points(body: UpsertIn):
    if not body.points:
        return {"upserted": 0, "collection": body.collection or QDRANT_DEFAULT_COLLECTION}
    coll = body.collection or QDRANT_DEFAULT_COLLECTION

    # Dim-Check
    dim = len(body.points[0].vector)
    if dim <= 0:
        raise HTTPException(400, detail="first point has empty vector")
    for p in body.points:
        if len(p.vector) != dim:
            raise HTTPException(400, detail="inconsistent vector dimensions within batch")

    _ensure_collection(coll, dim)
    cli = _client()
    # Upsert
    cli.upsert(
        collection_name=coll,
        points=[p.dict() for p in body.points],
        wait=bool(body.wait)
    )
    return {"upserted": len(body.points), "collection": coll, "dim": dim}

@router.get("/collections")
def list_collections():
    cli = _client()
    out = []
    res = cli.get_collections()
    for c in res.collections or []:
        name = c.name
        try:
            meta = cli.get_collection(name)
            out.append({
                "name": name,
                "status": str(getattr(meta, "status", "")),
                "vectors_count": int(getattr(meta, "points_count", 0)),
                "config": {
                    "on_disk": QDRANT_ON_DISK if name == QDRANT_DEFAULT_COLLECTION else None
                }
            })
        except Exception as e:
            out.append({"name": name, "error": str(e)})
    return {"items": out}

@router.get("/health")
def health():
    try:
        _client().get_collections()
        ok = True
    except Exception as e:
        ok = False
        return {"ok": ok, "error": str(e), "url": QDRANT_URL}
    return {"ok": ok, "url": QDRANT_URL}
