# rag-backend/app/deps.py (Ausschnitt)
import os
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.embedders.ollama import (
    OllamaDocumentEmbedder,
    OllamaTextEmbedder,
)
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
from haystack_integrations.components.generators.ollama import OllamaGenerator

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "mxbai-embed-large")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", "llama3")

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")

def get_document_store() -> QdrantDocumentStore:
    return QdrantDocumentStore(url=QDRANT_URL, index=QDRANT_COLLECTION, recreate_index=False)

# NEU: Für Indexierung (Documents -> embeddings)
def get_doc_embedder() -> OllamaDocumentEmbedder:
    return OllamaDocumentEmbedder(model=EMBED_MODEL, url=OLLAMA_BASE_URL)

# NEU: Für Query (Query-Text -> embedding)
def get_text_embedder() -> OllamaTextEmbedder:
    return OllamaTextEmbedder(model=EMBED_MODEL, url=OLLAMA_BASE_URL)

def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    return QdrantEmbeddingRetriever(document_store=store)

def get_generator() -> OllamaGenerator:
    return OllamaGenerator(model=GENERATOR_MODEL, url=OLLAMA_BASE_URL)
