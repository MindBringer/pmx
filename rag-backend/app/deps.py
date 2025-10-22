# app/deps.py
# -------------------------------------------------
# Zentraler Dependency-Loader für RAG-Backend
# (Haystack 2.18+ mit Qdrant und OpenAI/vLLM Support)
# -------------------------------------------------

import os
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.embedders.sentence_transformers import SentenceTransformersTextEmbedder, SentenceTransformersDocumentEmbedder
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
from haystack_integrations.components.generators.openai import OpenAIGenerator


# -------------------------------------------------
# 🔧 ENV-Defaults
# -------------------------------------------------
def _int_env(name: str, default: int) -> int:
    """Hole Umgebungsvariable als int, mit Default."""
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


# Basis-Konfiguration
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")
QDRANT_RECREATE = os.getenv("QDRANT_RECREATE", "false").lower() == "true"

# Embedding & Generator Modelle
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_DIM = _int_env("EMBED_DIM", 384)

# OpenAI-kompatible LLMs (z. B. vLLM, local LLM proxy, Mistral, etc.)
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "gpt-4o-mini")
GENERATOR_API_BASE = os.getenv("GENERATOR_API_BASE", "http://192.168.30.43:8001/v1")
GENERATOR_API_KEY = os.getenv("GENERATOR_API_KEY", "change-me")


# -------------------------------------------------
# 🧠 Komponenten-Fabriken
# -------------------------------------------------

def get_document_store() -> QdrantDocumentStore:
    """Erzeuge Qdrant Document Store."""
    return QdrantDocumentStore(
        url=QDRANT_URL,
        index=QDRANT_COLLECTION,
        embedding_dim=EMBED_DIM,
        similarity="cosine",
        recreate_index=QDRANT_RECREATE,
    )


def get_doc_embedder() -> SentenceTransformersDocumentEmbedder:
    """Embedding für Dokumente."""
    return SentenceTransformersDocumentEmbedder(model=EMBED_MODEL)


def get_text_embedder() -> SentenceTransformersTextEmbedder:
    """Embedding für Query/Text."""
    return SentenceTransformersTextEmbedder(model=EMBED_MODEL)


def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    """Retriever: Qdrant-ähnliche Embeddings."""
    return QdrantEmbeddingRetriever(document_store=store)


def get_generator() -> OpenAIGenerator:
    """
    Generator nutzt OpenAI-kompatibles API — ideal für vLLM oder lokales Gateway.
    Erfordert:
      - GENERATOR_API_BASE (z. B. http://192.168.30.43:8001/v1)
      - GENERATOR_API_KEY
    """
    return OpenAIGenerator(
        model=GENERATOR_MODEL,
        api_key=GENERATOR_API_KEY,
        api_base_url=GENERATOR_API_BASE,
        generation_kwargs={"temperature": 0.3, "max_tokens": 1024},
    )


# -------------------------------------------------
# 🧩 Diagnoseausgabe (optional)
# -------------------------------------------------
if __name__ == "__main__":
    print("✅ deps.py loaded successfully")
    print(f"Qdrant URL: {QDRANT_URL}")
    print(f"Embed Model: {EMBED_MODEL}")
    print(f"Generator: {GENERATOR_MODEL} via {GENERATOR_API_BASE}")
