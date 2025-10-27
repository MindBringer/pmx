# app/deps.py
import os
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever

# --- SentenceTransformers (lokal) ---
from haystack.components.embedders import (
    SentenceTransformersTextEmbedder,
    SentenceTransformersDocumentEmbedder,
)
from haystack.utils import ComponentDevice

# --- Generator (lokal OpenAI-kompatibel, z. B. vLLM) ---
from haystack.components.generators import OpenAIGenerator
from haystack.utils import Secret


# =====================================================
# ENV + Utility
# =====================================================

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


# --- Qdrant ---
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")
QDRANT_TIMEOUT = _int_env("QDRANT_TIMEOUT", 30)
QDRANT_RECREATE = os.getenv("QDRANT_RECREATE", "false").lower() == "true"

# --- Embeddings ---
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_DIM = _int_env("EMBED_DIM", 384)
EMBED_DEVICE = os.getenv("EMBED_DEVICE", os.getenv("DEVICE", "cpu"))  # kompatibel zu älteren Envs

# --- Generator (lokal via vLLM/OpenAI-kompatibel) ---
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://vllm-allrounder:8000/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "local-anything")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct")


# =====================================================
# Document Store / Retriever
# =====================================================

def get_document_store() -> QdrantDocumentStore:
    """Erstellt oder verbindet sich mit lokalem Qdrant-Store."""
    return QdrantDocumentStore(
        url=QDRANT_URL,
        index=QDRANT_COLLECTION,
        embedding_dim=EMBED_DIM,
        similarity="cosine",
        recreate_index=QDRANT_RECREATE,
        timeout=QDRANT_TIMEOUT,
    )


def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    """Retriever für semantische Suche in Qdrant."""
    return QdrantEmbeddingRetriever(document_store=store)

# =====================================================
# Embedders – neue Instanz je Pipeline, aber jedes Mal warm_up()
# =====================================================

from time import perf_counter

def _warmup(embedder, kind: str):
    """Hilfsfunktion mit Timer-Log."""
    t0 = perf_counter()
    embedder.warm_up()
    dt = perf_counter() - t0
    print(f"[warmup] {kind} ready in {dt:.2f}s")


def get_doc_embedder() -> SentenceTransformersDocumentEmbedder:
    """Document Embedder – neue Instanz, warm_up() bei jeder Erzeugung."""
    embedder = SentenceTransformersDocumentEmbedder(
        model=EMBED_MODEL,
        device=ComponentDevice.from_str(EMBED_DEVICE),
        normalize_embeddings=True,
    )
    _warmup(embedder, f"DocumentEmbedder {EMBED_MODEL}")
    return embedder


def get_text_embedder() -> SentenceTransformersTextEmbedder:
    """Text Embedder – neue Instanz, warm_up() bei jeder Erzeugung."""
    embedder = SentenceTransformersTextEmbedder(
        model=EMBED_MODEL,
        device=ComponentDevice.from_str(EMBED_DEVICE),
        normalize_embeddings=True,
    )
    _warmup(embedder, f"TextEmbedder {EMBED_MODEL}")
    return embedder


# =====================================================
# Generator (lokal via vLLM)
# =====================================================

def get_generator() -> OpenAIGenerator:
    """
    Generator für vLLM (OpenAI-kompatibel, lokal).
    Kein externer Traffic, nutzt OpenAI-kompatibles Gateway (http://vllm-allrounder:8000/v1).
    """
    api_key_secret = Secret.from_token(OPENAI_API_KEY)
    print(f"[init] Initialisiere OpenAIGenerator mit {GENERATOR_MODEL} @ {OPENAI_BASE_URL}")

    return OpenAIGenerator(
        api_key=api_key_secret,
        api_base_url=OPENAI_BASE_URL,
        model=GENERATOR_MODEL,
        generation_kwargs={
            "max_tokens": 2048,
            "temperature": 0.7,
        },
    )
