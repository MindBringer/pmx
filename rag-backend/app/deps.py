import os
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
from haystack_integrations.components.generators.ollama import OllamaGenerator
from haystack_integrations.components.embedders.ollama import OllamaTextEmbedder

QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "pmx_docs")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

LLM_MODEL = os.getenv("LLM_MODEL", "llama3:8b-instruct")
GENERATOR_MODEL = os.getenv("GENERATOR_MODEL", LLM_MODEL)
EMBED_MODEL = os.getenv("EMBED_MODEL", "mxbai-embed-large")

def get_document_store() -> QdrantDocumentStore:
    return QdrantDocumentStore(url=QDRANT_URL, index=QDRANT_COLLECTION, recreate_index=False)

def get_embedder() -> OllamaTextEmbedder:
    return OllamaTextEmbedder(model=EMBED_MODEL, url=OLLAMA_BASE_URL)

def get_generator():
    return OllamaGenerator(model=GENERATOR_MODEL, url=OLLAMA_BASE_URL)

def get_retriever(store: QdrantDocumentStore) -> QdrantEmbeddingRetriever:
    return QdrantEmbeddingRetriever(document_store=store)
