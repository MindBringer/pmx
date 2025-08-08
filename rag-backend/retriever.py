import os
from llama_index.core.indices.vector_store.base import VectorStoreIndex
from llama_index.readers.llama_index_readers import SimpleDirectoryReader
from llama_index.core.storage.storage_context import StorageContext
from llama_index.core.indices.loading import load_index_from_storage
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.ollama import Ollama

STORAGE_DIR = "./storage"
DOCS_DIR = "./documents"

def build_or_load_index():
    embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")
    llm_model = Ollama(model="llama3", host="http://ollama-llama3:11434")

    service_context = {
        "embed_model": embed_model,
        "llm": llm_model
    }

    if os.path.exists(STORAGE_DIR) and os.listdir(STORAGE_DIR):
        index = VectorStoreIndex.load_from_disk(STORAGE_DIR, service_context=service_context)
    else:
        documents = SimpleDirectoryReader(DOCS_DIR).load_data()
        index = VectorStoreIndex.from_documents(documents, service_context=service_context)
        index.save_to_disk(STORAGE_DIR)
    return index

def query_index(question: str, top_k: int = 3) -> str:
    index = build_or_load_index()
    response = index.query(question, similarity_top_k=top_k)
    return str(response)
