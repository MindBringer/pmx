# app/deps.py
import os

# --- Qdrant Integration ---
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever

# --- SentenceTransformers (lokale Embeddings) ---
from haystack.components.embedders.sentence_transformers import (
    SentenceTransformersTextEmbedder,
    SentenceTransformersDocumentEmbedder,
)

# --- Generator (OpenAI oder vLLM-kompatibel) ---
from haystack.components.generators.openai import OpenAIGenerator


# --- Utility: ENV-Helper ---
def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


# --- ENV Defaults ---
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_DIM = _int_env("EMBED_DIM", 384)
QDRANT_RECREATE = os.getenv("QDRANT_RECREATE", "false").lower() == "true"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "change-me")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "gpt-4o-mini")


# --- Factories ---
def get_document_store() -> QdrantDocumentStore:
    return QdrantDocumentStore(
        url=QDRANT_URL,
        index=QDRANT_COLLECTION,
        embedding_dim=EMBED_DIM,
        similarity="cosine",
        recreate_index=QDRANT_RECREATE,
    )


def get_doc_embedder() -> SentenceTransformersDocumentEmbedder:
    return SentenceTransformersDocumentEmbedder(model=EMBED_MODEL)


def get_text_embedder() -> SentenceTransformersTextEmbedder:
    return SentenceTransformersTextEmbedder(model=EMBED_MODEL)


def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    return QdrantEmbeddingRetriever(document_store=store)


def get_generator() -> OpenAIGenerator:
    return OpenAIGenerator(api_key=OPENAI_API_KEY, model=GENERATOR_MODEL)
