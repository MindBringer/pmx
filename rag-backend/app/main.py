# rag-backend/app/main.py

import os
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Depends, Header, HTTPException, Form
from jinja2 import Environment, StrictUndefined

from haystack import Document

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
    # 3b) Direkter Ollama-Call (um Haystack-Wrapper-/Pydantic-Kanten zu vermeiden)
    try:
        from collections.abc import Mapping
    except Exception:
        Mapping = dict  # fallback

    # prompt war oben bereits als String gerendert; trotzdem defensiv normalisieren:
    if isinstance(prompt, Mapping) and "prompt" in prompt and isinstance(prompt["prompt"], str):
        prompt = prompt["prompt"]
    elif not isinstance(prompt, str):
        prompt = str(prompt)

    try:
        from ollama import Client as _OClient
        ollama_host = os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL") or "http://ollama:11434"
        model_name = os.getenv("OLLAMA_MODEL") or os.getenv("GENERATOR_MODEL") or "llama3"
        _oc = _OClient(host=ollama_host)
        _resp = _oc.generate(model=model_name, prompt=prompt, stream=False)
        answer = (_resp.get("response") or "").strip()
    except Exception as _e:
        # Fallback: versuche trotzdem den Haystack-Generator (falls konfiguriert)
        try:
            gen = get_generator()
            gen_out = gen.run({"prompt": prompt}) or {}
            answer_list = gen_out.get("replies") or []
            answer = answer_list[0] if answer_list else ""
        except Exception as _e2:
            raise HTTPException(status_code=500, detail=f"Ollama/Generator error: {str(_e2) or str(_e)}")
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