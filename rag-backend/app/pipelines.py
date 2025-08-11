from typing import List, Optional
from haystack import Pipeline, Document
from haystack.components.routers import FileTypeRouter
from haystack.components.converters import PyPDFToDocument, TextFileToDocument, MarkdownToDocument, HTMLToDocument
from haystack.components.preprocessors import DocumentCleaner, DocumentSplitter
from haystack.components.writers import DocumentWriter
from .deps import get_document_store, get_embedder, get_retriever, get_generator
from .tagging import extract_tags
import os

def int_env(k, d):
    try: return int(os.getenv(k, d))
    except: return d

def build_index_pipeline():
    store = get_document_store()
    embedder = get_embedder()
    writer = DocumentWriter(document_store=store)

    router = FileTypeRouter(mime_types={
        "application/pdf": "pdf",
        "text/plain": "txt",
        "text/markdown": "md",
        "text/html": "html",
    })
    pdf = PyPDFToDocument()
    txt = TextFileToDocument()
    md  = MarkdownToDocument()
    htm = HTMLToDocument()

    cleaner = DocumentCleaner()
    splitter = DocumentSplitter(split_by="token", split_length=int_env("CHUNK_SIZE", 1200),
                                split_overlap=int_env("CHUNK_OVERLAP", 120))

    pipe = Pipeline()
    pipe.add_component("router", router)
    pipe.add_component("pdf", pdf); pipe.add_component("txt", txt)
    pipe.add_component("md", md);   pipe.add_component("html", htm)
    pipe.add_component("clean", cleaner)
    pipe.add_component("split", splitter)
    pipe.add_component("embed", embedder)
    pipe.add_component("write", writer)

    pipe.connect("router.pdf", "pdf.sources")
    pipe.connect("router.txt", "txt.sources")
    pipe.connect("router.md",  "md.sources")
    pipe.connect("router.html","html.sources")

    for n in ("pdf", "txt", "md", "html"):
        pipe.connect(f"{n}.documents", "clean.documents")
    pipe.connect("clean.documents", "split.documents")
    pipe.connect("split.documents", "embed.documents")
    pipe.connect("embed.documents", "write.documents")
    return pipe, store

def postprocess_with_tags(gen, docs: List[Document], default_tags: Optional[List[str]]):
    for d in docs:
        auto = extract_tags(gen, d.content)[:8]
        meta = d.meta or {}
        tags = sorted(set((meta.get("tags") or []) + auto + (default_tags or [])))
        meta["tags"] = tags
        d.meta = meta
    return docs

def build_query_pipeline(store=None):
    store = store or get_document_store()
    retriever = get_retriever(store)
    gen = get_generator()

    pipe = Pipeline()
    pipe.add_component("retrieve", retriever)
    pipe.add_component("generate", gen)
    pipe.connect("retrieve", "generate.documents")
    return pipe
