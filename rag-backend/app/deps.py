# app/deps.py — kompatibel mit haystack-ai >= 3.3
# app/deps.py – kompatibel mit haystack-ai >= 3.3 + qdrant-haystack >= 9
import os
from qdrant_haystack import QdrantDocumentStore
from haystack.components.embedders import (
    SentenceTransformersDocumentEmbedder,
    SentenceTransformersTextEmbedder,
)
from haystack.components.retrievers.qdrant import QdrantEmbeddingRetriever
from haystack.components.generators.openai import OpenAIGenerator

def _int_env(name: str, default: int) -> int:
    """Hole eine Umgebungsvariable als int, mit Default."""
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# --- Konfiguration über ENV ---
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "change-me")
EMBED_DIM = int(os.getenv("EMBED_DIM", "384"))
QDRANT_RECREATE = os.getenv("QDRANT_RECREATE", "false").lower() == "true"


# --- Komponenten-Factories ---

def get_document_store() -> QdrantDocumentStore:
    """Qdrant als persistenten Document Store initialisieren."""
    return QdrantDocumentStore(
        url=QDRANT_URL,
        index=QDRANT_COLLECTION,
        embedding_dim=EMBED_DIM,
        similarity="cosine",
        recreate_index=QDRANT_RECREATE,
    )


def get_doc_embedder() -> SentenceTransformersDocumentEmbedder:
    """Für Indexierung (Documents -> embeddings)."""
    return SentenceTransformersDocumentEmbedder(model=EMBED_MODEL)


def get_text_embedder() -> SentenceTransformersTextEmbedder:
    """Für Query-Embedding (Query -> Vektor)."""
    return SentenceTransformersTextEmbedder(model=EMBED_MODEL)


def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    """Retriever nutzt den Qdrant Store."""
    return QdrantEmbeddingRetriever(document_store=store)


def get_generator() -> OpenAIGenerator:
    """LLM-Generator für Antworten und Zusammenfassungen."""
    return OpenAIGenerator(
        api_key=OPENAI_API_KEY,
        model=GENERATOR_MODEL,
        timeout=300,
        generation_kwargs={"temperature": 0.3, "max_tokens": 1000},
    )
