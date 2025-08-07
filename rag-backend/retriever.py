import os
from llama_index.storage.storage_context import StorageContext
from llama_index.indices.vector_store import VectorStoreIndex
from llama_index.indices.utils import load_index_from_storage
from llama_index.readers import SimpleDirectoryReader
from llama_index.embeddings import OllamaEmbedding

STORAGE_DIR = "./storage"
DOCS_DIR = "./documents"

def build_or_load_index():
    embed_model = OllamaEmbedding(
        model="llama3",
        host="http://ollama-llama3:11434"
    )

    if os.path.exists(STORAGE_DIR) and os.listdir(STORAGE_DIR):
        storage_context = StorageContext.from_defaults(persist_dir=STORAGE_DIR)
        return load_index_from_storage(storage_context=storage_context)
    else:
        documents = SimpleDirectoryReader(DOCS_DIR).load_data()
        index = VectorStoreIndex.from_documents(documents, embed_model=embed_model)
        index.storage_context.persist(persist_dir=STORAGE_DIR)
        return index

def query_index(question: str, top_k: int = 3) -> str:
    index = build_or_load_index()
    query_engine = index.as_query_engine(similarity_top_k=top_k)
    response = query_engine.query(question)
    return str(response)
