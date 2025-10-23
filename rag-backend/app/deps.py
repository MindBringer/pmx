# app/deps.py
import os

# --- Qdrant Integration ---
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever

# --- SentenceTransformers (direkt in Haystack 2.x) ---
from haystack.components.embedders import (
    SentenceTransformersTextEmbedder,
    SentenceTransformersDocumentEmbedder,
)

# --- Generator (OpenAI-kompatibel, funktioniert mit vLLM) ---
from haystack.components.generators import OpenAIGenerator
from haystack.utils import Secret


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

# vLLM als OpenAI-kompatibler Endpoint
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "dummy-key")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://vllm:8000/v1")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "meta-llama/Meta-Llama-3.1-8B-Instruct")


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
    """
    Generator für vLLM (OpenAI-kompatibel)
    
    Haystack 2.x benötigt Secret-Objekte statt plain strings für API-Keys.
    """
    # Secret-Objekt erstellen (vLLM braucht oft keinen echten Key)
    api_key_secret = Secret.from_token(OPENAI_API_KEY)
    
    return OpenAIGenerator(
        api_key=api_key_secret,
        api_base_url=OPENAI_BASE_URL,
        model=GENERATOR_MODEL,
        generation_kwargs={
            "max_tokens": 2048,
            "temperature": 0.7,
        }
    )