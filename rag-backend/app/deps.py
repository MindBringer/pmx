# rag-backend/app/deps.py (Ausschnitt)
import os
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.embedders.ollama import (
    OllamaDocumentEmbedder,
    OllamaTextEmbedder,
)
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
from haystack_integrations.components.generators.ollama import OllamaGenerator

def _int_env(name: str, default: int) -> int:
    """Hole eine Umgebungsvariable als int, mit Default."""
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "mxbai-embed-large")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "llama3")
OLLAMA_TIMEOUT = _int_env("OLLAMA_TIMEOUT", 300)  # Sekunden (z.B. 300 = 5min)

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")

# NEU: Embedding-Dimension konfigurieren (mxbai-embed-large = 1024)
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))
# Optional: einmalige Neuerstellung per ENV steuerbar
QDRANT_RECREATE = os.getenv("QDRANT_RECREATE", "false").lower() == "true"

def get_document_store() -> QdrantDocumentStore:
    return QdrantDocumentStore(
        url=QDRANT_URL,
        index=QDRANT_COLLECTION,
        embedding_dim=EMBED_DIM,   # <<< WICHTIG
        similarity="cosine",
        recreate_index=QDRANT_RECREATE,

    )

# NEU: Für Indexierung (Documents -> embeddings)
def get_doc_embedder() -> OllamaDocumentEmbedder:
    return OllamaDocumentEmbedder(model=EMBED_MODEL, url=OLLAMA_BASE_URL, timeout=OLLAMA_TIMEOUT)

# NEU: Für Query (Query-Text -> embedding)
def get_text_embedder() -> OllamaTextEmbedder:
    return OllamaTextEmbedder(model=EMBED_MODEL, url=OLLAMA_BASE_URL, timeout=OLLAMA_TIMEOUT)

def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    return QdrantEmbeddingRetriever(document_store=store)

def get_generator() -> OllamaGenerator:
    return OllamaGenerator(model=GENERATOR_MODEL, url=OLLAMA_BASE_URL, timeout=OLLAMA_TIMEOUT)
