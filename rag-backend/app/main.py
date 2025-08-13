# rag-backend/app/main.py

import os
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Depends, Header, HTTPException, Form

from haystack import Document

from .models import IndexRequest, QueryRequest, QueryResponse, TagPatch
from .deps import get_document_store, get_generator, get_retriever, get_text_embedder
from .pipelines import (
    build_index_pipeline,
    build_query_pipeline,
    postprocess_with_tags,
    convert_bytes_to_documents,
)

from .transcribe import router as transcribe_router

# -----------------------------
# Settings & App
# -----------------------------
API_KEY = os.getenv("API_KEY", "")
BASE_PATH = os.getenv("RAG_BASE_PATH", "/rag")
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0"))  # 0 = aus

app = FastAPI(title="pmx-rag-backend", version="1.0.0")

app.include_router(transcribe_router, prefix="/rag", tags=["audio"])

def require_key(x_api_key: Optional[str] = Header(None)):
    """
    Einfacher Header-Check. Setze API_KEY in rag-backend/.env
    """
    # Wenn ein Key gesetzt ist, muss er passen.
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


# -----------------------------
# Health
# -----------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


# -----------------------------
# Index
# -----------------------------
@app.post("/index", dependencies=[Depends(require_key)])
async def index(
    files: List[UploadFile] = File(default=[]),
    tags: Optional[List[str]] = Form(default=None),   # <— NEU
):
    # Pipeline-Komponenten
    pipe, _store = build_index_pipeline()
    gen = get_generator()

    all_docs: List[Document] = []
    file_stats = []

    for f in files:
        data = await f.read()
        mime = f.content_type or "application/octet-stream"
        docs = convert_bytes_to_documents(
            filename=f.filename,
            mime=mime,
            data=data,
            default_meta={"source": "upload"},
        )
        # Auto-Tagging auf Chunk-Basis + Form-Tags
        docs = postprocess_with_tags(gen, docs, tags or [])
        all_docs.extend(docs)
        file_stats.append({"filename": f.filename, "chunks": len(docs)})

    if not all_docs:
        return {"indexed": 0, "files": file_stats}

    _ = pipe.run({"clean": {"documents": all_docs}})
    return {"indexed": len(all_docs), "files": file_stats}

# -----------------------------
# Query
# -----------------------------
@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_key)])
def query(payload: QueryRequest):
    """
    Semantische Suche + Generierung.
    Unterstützt Tag-Filter:
      - tags_all: alle müssen enthalten sein
      - tags_any: mindestens einer muss enthalten sein
    """
    store = get_document_store()
    pipe = build_query_pipeline(store)

    # Filter bauen (Qdrant-Dokumentfilter)
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
        "retrieve":    {"filters": flt, "top_k": payload.top_k or 5},
        "prompt_builder": {"query": payload.query},
        "generate": {}
    })

# Antwort aus der Pipeline
    gen_out = ret.get("generate", {}) if isinstance(ret, dict) else {}
    answer_list = gen_out.get("replies") or []
    answer = answer_list[0] if answer_list else ""

# Quellen separat via Direkt-Retrieval (robust, unabhängig von Pipeline-Outputs)
    store = get_document_store()
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

# Quellen zusammenfassen
    srcs = []
    for d in docs:
        meta = getattr(d, "meta", {}) or {}
        srcs.append({
            "id": getattr(d, "id", None),
            "score": getattr(d, "score", None),
            "tags": meta.get("tags"),
            "meta": meta,
            "snippet": (getattr(d, "content", "") or "")[:350],
        })

    used_tags = sorted({t for d in docs for t in ((getattr(d, "meta", None) or {}).get("tags", []))})

# Antworttext um kompakte Quellenliste ergänzen
    if srcs:
        lines = []
        for s in srcs[:5]:
            fname = (s.get("meta") or {}).get("filename") or (s.get("meta") or {}).get("file_path") or s["id"]
            sc = s.get("score")
            lines.append(f"- {fname} (score: {sc:.3f})" if sc is not None else f"- {fname}")
        answer = f"{answer}\n\nQuellen:\n" + "\n".join(lines)

    return QueryResponse(answer=answer, sources=srcs, used_tags=used_tags)

# -----------------------------
# Tags
# -----------------------------
@app.get("/tags", dependencies=[Depends(require_key)])
def list_tags(limit: int = 1000):
    """
    Aggregiert alle bekannten Tags und liefert Counts zurück.
    """
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
    """
    Ermöglicht das manuelle Hinzufügen/Entfernen von Tags an einem Dokument.
    """
    store = get_document_store()
    # Einfachster Weg: Dokument anhand der ID holen
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
