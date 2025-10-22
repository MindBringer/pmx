# app/deps.py — Haystack 3.x (vLLM + SentenceTransformers + Qdrant)

import os
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.embedders.sentence_transformers import SentenceTransformersTextEmbedder
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
from haystack_integrations.components.generators.openai import OpenAIGenerator


# ---------------------------
# Environment Defaults
# ---------------------------

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")
QDRANT_RECREATE = os.getenv("QDRANT_RECREATE", "false").lower() == "true"

# Lokaler SentenceTransformer für Embeddings
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))  # MiniLM hat 384 Dimensionen

# vLLM / OpenAI-kompatibles LLM
LLM_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://192.168.30.43:8001/v1")
LLM_API_KEY = os.getenv("OPENAI_API_KEY", "change-me")
LLM_MODEL = os.getenv("GENERATOR_MODEL", "gpt-4o-mini")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))


# ---------------------------
# Komponenten-Factories
# ---------------------------

def get_document_store() -> QdrantDocumentStore:
    """Initialisiert Qdrant Document Store."""
    return QdrantDocumentStore(
        url=QDRANT_URL,
        index=QDRANT_COLLECTION,
        embedding_dim=EMBED_DIM,
        similarity="cosine",
        recreate_index=QDRANT_RECREATE,
    )


def get_doc_embedder() -> SentenceTransformersTextEmbedder:
    """Embedder für Dokumente."""
    return SentenceTransformersTextEmbedder(model=EMBED_MODEL)


def get_text_embedder() -> SentenceTransformersTextEmbedder:
    """Embedder für Queries."""
    return SentenceTransformersTextEmbedder(model=EMBED_MODEL)


def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    """Retriever für semantische Suche."""
    return QdrantEmbeddingRetriever(document_store=store)


def get_generator() -> OpenAIGenerator:
    """
    Generator für Text-Antworten (vLLM/OpenAI-kompatibel).
    Erwartet: OPENAI_BASE_URL → z. B. http://192.168.30.43:8001/v1
    """
    return OpenAIGenerator(
        api_key=LLM_API_KEY,
        model=LLM_MODEL,
        base_url=LLM_BASE_URL,
        timeout=LLM_TIMEOUT,
    )
