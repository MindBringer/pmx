# rag-backend/app/main.py

import os, time
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Depends, Header, HTTPException, Form, Request
from haystack import Document

from .models import IndexRequest, QueryRequest, QueryResponse, TagPatch
from .deps import get_document_store, get_generator, get_retriever, get_text_embedder
from .pipelines import (
    build_index_pipeline,
    build_query_pipeline,
    postprocess_with_tags,
    convert_bytes_to_documents,
)

from .transcribe import router as transcribe_router  # Audio: /transcribe + /speakers
from .jobs import router as jobs_router
app.include_router(jobs_router, prefix="/rag")

# -----------------------------
# Settings & App
# -----------------------------
API_KEY = os.getenv("API_KEY", "")
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0"))  # 0 = aus

app = FastAPI(title="pmx-rag-backend", version="1.0.0")

# Neue Audio-/Speaker-Routen einhängen (aus transcribe.py)
app.include_router(transcribe_router, prefix="", tags=["audio"])


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
    request: Request,
    files: List[UploadFile] = File(default=[]),
):
    """
    Mehrere Dateien entgegennehmen, in Haystack-Dokumente konvertieren,
    automatisch taggen (inkl. Form-Tags) und indexieren.
    Liefert Metadaten: Chunks, Laufzeiten, Dateigröße etc.
    """
    # --- Tags robust aus dem Form auslesen (String, CSV oder mehrfach) ---
    form = await request.form()
    raw_list = form.getlist("tags")
    tags: List[str] = []
    if raw_list:
        for item in raw_list:
            if isinstance(item, str) and ("," in item):
                tags.extend([t.strip() for t in item.split(",") if t.strip()])
            elif isinstance(item, str) and item.strip():
                tags.append(item.strip())
    else:
        raw = form.get("tags")
        if isinstance(raw, str) and raw.strip():
            tags = [t.strip() for t in raw.split(",")] if "," in raw else [raw.strip()]

    # Pipelines
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
        # Auto-Tagging auf Chunk-Basis + Form-Tags
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

    # End-to-End Pipeline (Embed -> Retrieve -> Prompt -> Generate)
    ret = pipe.run({
        "embed_query":     {"text": payload.query},
        "retrieve":        {"filters": flt, "top_k": payload.top_k or 5},
        "prompt_builder":  {"query": payload.query},
        "generate":        {}
    })

    # Antwort aus der Pipeline
    gen_out = ret.get("generate", {}) if isinstance(ret, dict) else {}
    answer_list = gen_out.get("replies") or []
    answer = answer_list[0] if answer_list else ""

    # Quellen separat via Direkt-Retrieval (robust, unabhängig von Pipeline-Outputs)
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
    # Duplikate entfernen, Reihenfolge grob beibehalten
    seen = set()
    used_tags = [t for t in used_tags if not (t in seen or seen.add(t))]

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
    # Dokument anhand der ID holen
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
