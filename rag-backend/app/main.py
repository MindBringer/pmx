# rag-backend/app/main.py

import os
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Depends, Header, HTTPException

from haystack import Document

from .models import IndexRequest, QueryRequest, QueryResponse, TagPatch
from .deps import get_document_store, get_generator, get_retriever, get_text_embedder
from .pipelines import (
    build_index_pipeline,
    build_query_pipeline,
    postprocess_with_tags,
    convert_bytes_to_documents,
)

# -----------------------------
# Settings & App
# -----------------------------
API_KEY = os.getenv("API_KEY", "")
BASE_PATH = os.getenv("RAG_BASE_PATH", "/rag")

app = FastAPI(title="pmx-rag-backend", version="1.0.0", root_path=BASE_PATH)


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
    payload: IndexRequest = Depends(IndexRequest),
):
    """
    Nimmt Uploads entgegen, konvertiert sie in Haystack-Documents,
    ergänzt Auto-Tags, schreibt Embeddings & speichert in Qdrant.
    """
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
        # Auto-Tagging auf Chunk-Basis + Default-Tags aus Request
        docs = postprocess_with_tags(gen, docs, payload.tags or [])
        all_docs.extend(docs)
        file_stats.append({"filename": f.filename, "chunks": len(docs)})

    if not all_docs:
        # kein harter Fehler; gibt nur Info zurück
        return {"indexed": 0, "files": file_stats}

    # Cleaner -> Splitter -> Embedder -> Writer
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

# Ergebnis der Pipeline (Antwort-Text)
    gen_out = ret.get("generate", {}) if isinstance(ret, dict) else {}
    answer_list = gen_out.get("replies") or []
    answer = answer_list[0] if answer_list else ""

# --- Quellen separat holen: Text -> Embedding -> Retriever ---
    store = get_document_store()
    retriever = get_retriever(store)
    qembed = get_text_embedder()

    emb = qembed.run(text=payload.query)["embedding"]
    ret_docs = retriever.run(
        query_embedding=emb,
        filters=flt,
        top_k=payload.top_k or 5,
    )
    docs = ret_docs.get("documents", []) or []

# Quellen zusammenfassen
    srcs = [
        {
            "id": getattr(d, "id", None),
            "score": getattr(d, "score", None),
            "tags": (getattr(d, "meta", None) or {}).get("tags"),
            "meta": getattr(d, "meta", None),
            "snippet": (getattr(d, "content", "") or "")[:350],
        }
        for d in docs
    ]
    used_tags = sorted({t for d in docs for t in ((getattr(d, "meta", None) or {}).get("tags", []))})

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
