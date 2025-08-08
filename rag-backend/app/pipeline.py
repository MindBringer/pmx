import os
from haystack.nodes import EmbeddingRetriever, PromptNode
from haystack.document_stores import QdrantDocumentStore
from haystack.pipelines import GenerativeQAPipeline
from dotenv import load_dotenv

load_dotenv()

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")

document_store = QdrantDocumentStore(
    url=os.getenv("QDRANT_URL", "http://qdrant:6333"),
    recreate_index=False,
    embedding_dim=384,
    index="rag-index"
)

retriever = EmbeddingRetriever(
    document_store=document_store,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    use_gpu=False
)

generator = PromptNode(
    model_name_or_path=OLLAMA_MODEL,
    api_base_url=OLLAMA_URL,
    api_key=None,
    max_length=512,
    model_kwargs={"temperature": 0.7},
    default_prompt_template="query"
)

rag_pipeline = GenerativeQAPipeline(generator=generator, retriever=retriever)
