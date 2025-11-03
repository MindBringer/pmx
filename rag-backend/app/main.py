# rag-backend/app/main.py
import os
import time
from datetime import datetime
from uuid import uuid4
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Depends, Header, HTTPException, Request
from haystack import Document

from .models import IndexRequest, QueryRequest, QueryResponse, TagPatch
from .deps import get_document_store, get_generator, get_retriever, get_text_embedder, get_doc_embedder
from .pipelines import (
    build_index_pipeline,
    build_query_pipeline,
    postprocess_with_tags,
    convert_bytes_to_documents,
)

from app.routers.transcribe import router as transcribe_router
from app.routers.diarize import router as diarize_router
from app.routers.identify import router as identify_router
from app.routers.speakers import router as speaker_router
from app.embed import router as embed_router
from app.qdrant_api import router as qdrant_router
from app.parse_document import router as parse_router
from .jobs import router as jobs_router


# -----------------------------
# Settings & App
# -----------------------------
API_KEY = os.getenv("API_KEY", "")
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0"))  # 0 = aus

app = FastAPI(title="pmx-rag-backend", version="1.0.3")

# Router registrieren
app.include_router(transcribe_router, prefix="", tags=["audio"])
app.include_router(diarize_router, prefix="", tags=["audio"])
app.include_router(identify_router, prefix="", tags=["audio"])
app.include_router(speaker_router, prefix="", tags=["audio"])
app.include_router(embed_router)
app.include_router(qdrant_router)
app.include_router(parse_router)
app.include_router(jobs_router, prefix="/rag")


# -----------------------------
# Header-Schutz
# -----------------------------
def require_key(x_api_key: Optional[str] = Header(None)):
    """Einfacher Header-Check."""
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# -----------------------------
# Health
# -----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# -----------------------------
# Index – Upload & JSON-Direkt
# -----------------------------
@app.post("/index", dependencies=[Depends(require_key)])
async def index(
    request: Request,
    files: List[UploadFile] = File(default=[]),
):
    """
    Indexiert Dokumente aus Datei-Upload oder JSON-Body.
    - Uploads (multipart/form-data): werden geparst, gechunkt, eingebettet
    - JSON (application/json): werden direkt mit Embeddings in Qdrant gespeichert
    """
    content_type = request.headers.get("content-type", "").lower()
    is_json = "application/json" in content_type

    # =============================
    # JSON-Upload (z. B. aus n8n)
    # =============================
    if is_json:
        try:
            payload = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

        collection = payload.get("collection", "pmx_docs")
        docs_raw = payload.get("documents") or []
        if not isinstance(docs_raw, list) or not docs_raw:
            return {"indexed": 0, "collection": collection}

        store = get_document_store()
        store.index = collection

        docs = []
        for d in docs_raw:
            if not isinstance(d, dict):
                continue

            text = d.get("text") or d.get("content") or ""
            if not text.strip():
                continue

            # --- Automatische eindeutige ID-Vergabe ---
            if d.get("id"):
                doc_id = str(d["id"])
            else:
                # Basis: Datumszeit + kurze UUID (z. B. document-20251103-153045-a1b2c3)
                ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
                doc_id = f"document-{ts}-{uuid4().hex[:6]}"

            meta = d.get("metadata") or d.get("meta") or {}
            doc = Document(id=doc_id, content=text, meta=meta)
            docs.append(doc)

        if not docs:
            return {"indexed": 0, "collection": collection}

        # 🔹 Embeddings erzeugen
        embedder = get_doc_embedder()
        t_emb0 = time.perf_counter()
        embedded = embedder.run(documents=docs)["documents"]
        emb_ms = round((time.perf_counter() - t_emb0) * 1000)

        # 🔹 In Qdrant schreiben (Overwrite erlaubt)
        t0 = time.perf_counter()
        store.write_documents(embedded, policy="overwrite")
        elapsed_ms = round((time.perf_counter() - t0) * 1000)

        print(f"[index] Direkt gespeichert: {len(docs)} docs in {collection} mit Embeddings")

        return {
            "indexed": len(docs),
            "collection": collection,
            "metrics": {
                "elapsed_ms": elapsed_ms,
                "embed_ms": emb_ms,
                "total_chunks": len(docs),
            },
        }

    # =============================
    # Datei-Upload (Standardmodus)
    # =============================
    form = await request.form()
    raw_list = form.getlist("tags")
    tags: List[str] = []
    if raw_list:
        for item in raw_list:
            if isinstance(item, str) and "," in item:
                tags.extend([t.strip() for t in item.split(",") if t.strip()])
            elif isinstance(item, str) and item.strip():
                tags.append(item.strip())
    else:
        raw = form.get("tags")
        if isinstance(raw, str) and raw.strip():
            tags = [t.strip() for t in raw.split(",")] if "," in raw else [raw.strip()]

    pipe, _store = build_index_pipeline()
    gen = get_generator()

    t0 = time.perf_counter()
    all_docs: List[Document] = []
    file_stats = []

    for f in files:
        data = await f.read()
        mime = f.content_type or "application/octet-stream"
        size_bytes = len(data)

        t_conv0 = time.perf_counter()
        docs = convert_bytes_to_documents(
            filename=f.filename,
            mime=mime,
            data=data,
            default_meta={"source": "upload"},
        )
        docs = postprocess_with_tags(gen, docs, tags or [])
        conv_ms = round((time.perf_counter() - t_conv0) * 1000)

        all_docs.extend(docs)
        file_stats.append({
            "filename": f.filename,
            "mime": mime,
            "size_bytes": size_bytes,
            "chunks": len(docs),
            "chars": sum(len(d.content or "") for d in docs),
            "conv_ms": conv_ms,
        })

    t_idx0 = time.perf_counter()
    if all_docs:
        _ = pipe.run({"clean": {"documents": all_docs}})
    pipeline_ms = round((time.perf_counter() - t_idx0) * 1000)
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    total_chunks = len(all_docs)

    return {
        "indexed": total_chunks,
        "files": file_stats,
        "tags": tags,
        "metrics": {
            "elapsed_ms": elapsed_ms,
            "pipeline_ms": pipeline_ms,
            "total_chunks": total_chunks,
            "files_count": len(file_stats),
        },
    }


# -----------------------------
# Query (semantische Suche)
# -----------------------------
@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_key)])
def query(payload: QueryRequest):
    collection = getattr(payload, "collection", None) or getattr(payload, "collection_name", None) or "pmx_docs"

    store = get_document_store()
    store.index = collection
    pipe = build_query_pipeline(store)

    flt = None
    if payload.tags_all or payload.tags_any:
        flt = {"operator": "AND", "conditions": []}
        if payload.tags_all:
            flt["conditions"].append(
                {"field": "meta.tags", "operator": "contains_all", "value": payload.tags_all}
            )
        if payload.tags_any:
            flt["conditions"].append(
                {"field": "meta.tags", "operator": "contains_any", "value": payload.tags_any}
            )

    ret = pipe.run({
        "embed_query": {"text": payload.query},
        "retrieve": {"filters": flt, "top_k": payload.top_k or 5},
        "prompt_builder": {"query": payload.query},
        "generate": {},
    })

    gen_out = ret.get("generate", {}) if isinstance(ret, dict) else {}
    answer_list = gen_out.get("replies") or []
    answer = answer_list[0] if answer_list else ""

    retriever = get_retriever(store)
    qembed = get_text_embedder()
    emb = qembed.run(text=payload.query)["embedding"]
    ret_docs = retriever.run(
        query_embedding=emb,
        filters=flt,
        top_k=payload.top_k or 5,
        score_threshold=(SCORE_THRESHOLD if SCORE_THRESHOLD > 0 else None),
    )
    docs = ret_docs.get("documents", []) or []

    srcs = []
    used_tags = []
    for d in docs:
        meta = d.meta or {}
        srcs.append({
            "id": getattr(d, "id", None),
            "score": getattr(d, "score", None),
            "tags": meta.get("tags", []),
            "source": meta.get("source"),
            "title": meta.get("title"),
            "snippet": d.content[:400] + ("…" if d.content and len(d.content) > 400 else ""),
        })
        used_tags.extend(meta.get("tags", []))
    seen = set()
    used_tags = [t for t in used_tags if not (t in seen or seen.add(t))]

    return QueryResponse(answer=answer, sources=srcs, used_tags=used_tags)


# -----------------------------
# Tags
# -----------------------------
@app.get("/tags", dependencies=[Depends(require_key)])
def list_tags(limit: int = 1000):
    store = get_document_store()
    docs = store.filter_documents(filters=None, top_k=limit)
    from collections import Counter
    c = Counter()
    for d in docs:
        for t in (d.meta or {}).get("tags", []):
            c[t] += 1
    return [{"tag": k, "count": v} for k, v in c.most_common()]


# -----------------------------
# Tags patchen
# -----------------------------
@app.patch("/docs/{doc_id}/tags", dependencies=[Depends(require_key)])
def patch_tags(doc_id: str, patch: TagPatch):
    store = get_document_store()
    docs = store.filter_documents(
        filters={"operator": "AND", "conditions": [{"field": "id", "operator": "==", "value": doc_id}]},
        top_k=1,
    )
    if not docs:
        raise HTTPException(status_code=404, detail="Document not found")

    d = docs[0]
    tags = set((d.meta or {}).get("tags", []))
    if patch.add:
        tags |= set(patch.add)
    if patch.remove:
        tags -= set(patch.remove)

    d.meta = dict(d.meta or {}, tags=sorted(tags))
    store.write_documents([d])
    return {"doc_id": doc_id, "tags": d.meta["tags"]}
