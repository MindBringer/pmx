# rag-backend/app/deps.py
# ----------------------------------------
# Version: vLLM + SentenceTransformer (kein Ollama mehr)
# ----------------------------------------

import os
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.embedders.sentence_transformers import (
    SentenceTransformersDocumentEmbedder,
    SentenceTransformersTextEmbedder,
)
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
from haystack_integrations.components.generators.openai import OpenAIGenerator


# --- Helper -----------------------------------------------------

def _int_env(name: str, default: int) -> int:
    """Hole eine Umgebungsvariable als int, mit Default."""
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# --- Environment ------------------------------------------------

# Qdrant
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))   # all-MiniLM = 384
QDRANT_RECREATE = os.getenv("QDRANT_RECREATE", "false").lower() == "true"

# vLLM / OpenAI-kompatibel
VLLM_URL = os.getenv("VLLM_URL", "http://192.168.30.43:8001/v1")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "gpt-4o-mini")  # kann beliebig sein
API_KEY = os.getenv("OPENAI_API_KEY", "dummy")  # vLLM akzeptiert Dummy-Key


# --- Document Store ---------------------------------------------

def get_document_store() -> QdrantDocumentStore:
    return QdrantDocumentStore(
        url=QDRANT_URL,
        index=QDRANT_COLLECTION,
        embedding_dim=EMBED_DIM,
        similarity="cosine",
        recreate_index=QDRANT_RECREATE,
    )


# --- Embedding --------------------------------------------------

def get_doc_embedder() -> SentenceTransformersDocumentEmbedder:
    """
    Embedder für Dokumente beim Indexieren.
    Lokal, kein API-Key nötig.
    """
    return SentenceTransformersDocumentEmbedder(
        model="sentence-transformers/all-MiniLM-L6-v2"
    )


def get_text_embedder() -> SentenceTransformersTextEmbedder:
    """
    Embedder für Query-Text.
    Ebenfalls lokal (CPU/GPU je nach System).
    """
    return SentenceTransformersTextEmbedder(
        model="sentence-transformers/all-MiniLM-L6-v2"
    )


# --- Retriever --------------------------------------------------

def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    return QdrantEmbeddingRetriever(document_store=store)


# --- Generator --------------------------------------------------

def get_generator() -> OpenAIGenerator:
    """
    Generator über vLLM (OpenAI-kompatible API).
    """
    return OpenAIGenerator(
        api_key=API_KEY,
        base_url=VLLM_URL,
        model=GENERATOR_MODEL,
    )
