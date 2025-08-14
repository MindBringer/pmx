# rag-backend/app/main.py

import os
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Depends, Header, HTTPException, Form

from haystack import Document
from haystack.components.builders import PromptBuilder  # direkter Einsatz in Schritt 3

from .models import QueryRequest, QueryResponse, TagPatch
from .deps import get_document_store, get_generator
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
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.65"))          # 0 = aus
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES", "25"))          # wie viele Retriever-Kandidaten vor Rerank

app = FastAPI(title="pmx-rag-backend", version="1.0.0")

# Transcribe-Endpoints registrieren
app.include_router(transcribe_router, prefix="", tags=["audio"])


def require_key(x_api_key: Optional[str] = Header(None)):
    """Einfacher Header-Check. Setze API_KEY in rag-backend/.env"""
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
    tags: Optional[List[str]] = Form(default=None),
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
# Reranker (CrossEncoder) – lazy init
# -----------------------------
_RERANKER = None

def get_reranker():
    """
    Lokaler CrossEncoder-Reranker (sentence-transformers).
    Wird nur genutzt, wenn wir nach dem Retriever manuell reranken.
    """
    global _RERANKER
    if _RERANKER is None:
        from sentence_transformers import CrossEncoder
        model_name = os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
        _RERANKER = CrossEncoder(model_name)
    return _RERANKER


def _apply_threshold_and_best_per_file(docs: List[Document], thr: float) -> List[Document]:
    """Filtert per Threshold und lässt pro Datei nur den besten Chunk übrig."""
    filtered = [d for d in docs if (getattr(d, "score", None) is not None and float(d.score) >= thr)]
    best_per_file = {}
    for d in filtered:
        meta = getattr(d, "meta", {}) or {}
        fn = meta.get("filename") or meta.get("file_path") or "unknown"
        if fn not in best_per_file or (best_per_file[fn].score or 0) < (d.score or 0):
            best_per_file[fn] = d
    return sorted(best_per_file.values(), key=lambda x: (x.score or 0.0), reverse=True)


def _format_sources_for_answer(srcs: List[dict], limit: int = 5) -> str:
    lines = []
    for s in srcs[:limit]:
        fname = (s.get("meta") or {}).get("filename") or (s.get("meta") or {}).get("file_path") or s.get("id")
        sc = s.get("score")
        lines.append(f"- {fname} (score: {sc:.3f})" if sc is not None else f"- {fname}")
    return "\n".join(lines)


PROMPT_TEMPLATE = """Beantworte prägnant und korrekt anhand der folgenden Dokumente.
Gib keine Inhalte wieder, die nicht im Kontext stehen.

Kontext:
{% for d in documents %}
- {{ d.content | truncate(600) }}
{% endfor %}

Frage: {{ query }}
"""


# Defensive check to avoid Jinja 'non template nodes'
assert isinstance(PROMPT_TEMPLATE, str), f"PROMPT_TEMPLATE must be str, got {type(PROMPT_TEMPLATE)}"
# -----------------------------
# Query (Retriever → CrossEncoder-Rerank → PromptBuilder (direkt) → Generator)
# -----------------------------
@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_key)])
def query(payload: QueryRequest):
    """
    Semantische Suche + Generierung.
    Tag-Filter:
      - tags_all: alle müssen enthalten sein
      - tags_any: mindestens einer muss enthalten sein
    """
    # 0) Pipeline mit Retriever (und ggf. integriertem Ranker – falls aktiviert/verfügbar)
    store = get_document_store()
    pipe = build_query_pipeline(store)

    # Qdrant-Filter bauen
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

    # 1) Nur bis zum Retriever laufen lassen → Kandidaten
    ret = pipe.run({
        "embed_query": {"text": payload.query},
        "retrieve":    {"filters": flt, "top_k": max(payload.top_k or 5, RERANK_CANDIDATES)},
    })
    docs = (ret.get("retrieve") or {}).get("documents", []) if isinstance(ret, dict) else []

    # 2) Manuelles Reranking (CrossEncoder)
    top_docs: List[Document] = []
    if docs:
        reranker = get_reranker()
        pairs = [(payload.query, (getattr(d, "content", "") or "")) for d in docs]
        scores = reranker.predict(pairs)
        for d, sc in zip(docs, scores):
            d.score = float(sc)

        thr = SCORE_THRESHOLD if SCORE_THRESHOLD > 0 else 0.0
        top_docs = _apply_threshold_and_best_per_file(docs, thr)
        top_docs = top_docs[: (payload.top_k or 5)]

    # 3) Prompt bauen & generieren – NICHT über die Pipeline, sondern direkt:
    pb = PromptBuilder(template=PROMPT_TEMPLATE, required_variables=["query", "documents"])
    pb_out = pb.run({"query": payload.query, "documents": top_docs, "template": PROMPT_TEMPLATE})
    prompt = pb_out.get("prompt", "")

    gen = get_generator()
    gen_out = gen.run({"prompt": prompt}) or {}
    answer_list = gen_out.get("replies") or []
    answer = answer_list[0] if answer_list else ""

    # 4) Quellen zusammenfassen
    srcs = []
    for d in top_docs:
        meta = getattr(d, "meta", {}) or {}
        srcs.append({
            "id": getattr(d, "id", None),
            "score": round(float(getattr(d, "score", 0.0)), 3) if getattr(d, "score", None) is not None else None,
            "tags": meta.get("tags"),
            "source": meta.get("source"),
            "meta": meta,
            "snippet": (getattr(d, "content", "") or "").replace("\n", " ")[:350],
        })

    used_tags = sorted({t for d in top_docs for t in ((getattr(d, "meta", None) or {}).get("tags", []))})

    if srcs:
        answer = f"{answer}\n\nQuellen:\n" + _format_sources_for_answer(srcs, limit=5)

    return QueryResponse(answer=answer, sources=srcs, used_tags=used_tags)


# -----------------------------
# Tags
# -----------------------------
@app.get("/tags", dependencies=[Depends(require_key)])
def list_tags(limit: int = 1000):
    """Aggregiert alle bekannten Tags und liefert Counts zurück."""
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
    """Manuelles Hinzufügen/Entfernen von Tags an einem Dokument."""
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
