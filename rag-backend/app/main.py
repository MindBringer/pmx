import os, io
from fastapi import FastAPI, UploadFile, File, Depends, Body, Header, HTTPException
from typing import List, Optional
from haystack import Document
from .models import IndexRequest, QueryRequest, QueryResponse, TagPatch
from .deps import get_document_store, get_generator
from .pipelines import build_index_pipeline, build_query_pipeline, postprocess_with_tags

API_KEY = os.getenv("API_KEY")
BASE_PATH = os.getenv("RAG_BASE_PATH", "/rag")

app = FastAPI(title="pmx-rag-backend", root_path=BASE_PATH)

def require_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

@app.get("/health")
def health():
    return {"status":"ok"}

@app.post("/index", dependencies=[Depends(require_key)])
async def index(files: List[UploadFile] = File(default=[]), payload: IndexRequest = Depends(IndexRequest)):
    pipe, store = build_index_pipeline()
    gen = get_generator()

    all_docs: List[Document] = []
    for f in files:
        data = await f.read()
        mime = f.content_type or "application/octet-stream"
        from haystack.components.converters import PyPDFToDocument, TextFileToDocument, MarkdownToDocument, HTMLToDocument
        if mime == "application/pdf":
            docs = PyPDFToDocument().run(sources=[io.BytesIO(data)])["documents"]
        elif mime in ("text/markdown",):
            docs = MarkdownToDocument().run(sources=[io.BytesIO(data)])["documents"]
        elif mime in ("text/html", "application/xhtml+xml"):
            docs = HTMLToDocument().run(sources=[io.BytesIO(data)])["documents"]
        else:
            docs = TextFileToDocument().run(sources=[io.BytesIO(data)])["documents"]
        all_docs.extend(docs)

    all_docs = postprocess_with_tags(gen, all_docs, payload.tags or [])
    _ = pipe.run({"clean": {"documents": all_docs}}) if all_docs else {"write": {"documents": []}}
    return {"indexed": len(all_docs)}

@app.post("/query", response_model=QueryResponse, dependencies=[Depends(require_key)])
def query(payload: QueryRequest):
    store = get_document_store()
    pipe = build_query_pipeline(store)
    flt = None
    if payload.tags_all or payload.tags_any:
        flt = {"operator":"AND","conditions":[]}
        if payload.tags_all:
            flt["conditions"].append({"field":"meta.tags","operator":"contains_all","value":payload.tags_all})
        if payload.tags_any:
            flt["conditions"].append({"field":"meta.tags","operator":"contains_any","value":payload.tags_any})

    ret = pipe.run({
        "retrieve": {"query": payload.query, "filters": flt, "top_k": payload.top_k},
        "generate": {"prompt": f"Beantworte prägnant. Nutze die gegebenen Dokumente als Quelle.\nFrage: {payload.query}"}
    })
    answer = ret["generate"]["replies"][0]
    docs = ret["generate"]["documents"]
    srcs = [{
        "id": d.id,
        "score": getattr(d, "score", None),
        "tags": (d.meta or {}).get("tags"),
        "meta": d.meta,
        "snippet": d.content[:350]
    } for d in docs]
    used_tags = sorted({t for d in docs for t in (d.meta or {}).get("tags", [])})
    return QueryResponse(answer=answer, sources=srcs, used_tags=used_tags)

@app.get("/tags", dependencies=[Depends(require_key)])
def list_tags(limit: int = 1000):
    store = get_document_store()
    docs = store.filter_documents(filters=None, top_k=limit)
    from collections import Counter
    c = Counter()
    for d in docs:
        for t in (d.meta or {}).get("tags", []):
            c[t]+=1
    return [{"tag":k,"count":v} for k,v in c.most_common()]

@app.patch("/docs/{doc_id}/tags", dependencies=[Depends(require_key)])
def patch_tags(doc_id: str, patch: TagPatch):
    store = get_document_store()
    docs = store.filter_documents(filters={"operator":"AND","conditions":[{"field":"id","operator":"==","value":doc_id}]}, top_k=1)
    if not docs:
        raise HTTPException(status_code=404, detail="Document not found")
    d = docs[0]
    tags = set((d.meta or {}).get("tags", []))
    if patch.add:    tags |= set(patch.add)
    if patch.remove: tags -= set(patch.remove)
    d.meta = dict(d.meta or {}, tags=sorted(tags))
    store.write_documents([d])
    return {"doc_id": doc_id, "tags": d.meta["tags"]}
