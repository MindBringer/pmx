#!/bin/bash
set -e

echo "📦 Installiere RAG-Backend..."

# Verzeichnis anlegen
mkdir -p rag-backend/documents rag-backend/storage
cd rag-backend

# Beispiel-Dokument
echo "OAuth2 ist ein Autorisierungsprotokoll zur sicheren Delegation..." > documents/oauth.txt

# 1. requirements.txt
cat > requirements.txt <<EOF
fastapi
uvicorn
llama-index
pypdf
python-multipart
aiofiles
sentence-transformers
transformers
torch

EOF

# 2. retriever.py
cat > retriever.py <<'EOF'
from llama_index import SimpleDirectoryReader, VectorStoreIndex, StorageContext, load_index_from_storage
from llama_index import LLMPredictor
from llama_index.embeddings import OllamaEmbedding
import os

STORAGE_DIR = "./storage"
DOCS_DIR = "./documents"

def build_or_load_index():
    embed_model = OllamaEmbedding(model="llama3", host="http://ollama-llama3:11434")

    if os.path.exists(STORAGE_DIR) and os.listdir(STORAGE_DIR):
        storage_context = StorageContext.from_defaults(persist_dir=STORAGE_DIR)
        return load_index_from_storage(storage_context)
    else:
        documents = SimpleDirectoryReader(DOCS_DIR).load_data()
        index = VectorStoreIndex.from_documents(documents, embed_model=embed_model)
        index.storage_context.persist(persist_dir=STORAGE_DIR)
        return index


def query_index(question: str, top_k: int = 3) -> str:
    index = build_or_load_index()
    query_engine = index.as_query_engine(similarity_top_k=top_k)
    return query_engine.query(question)
EOF

# 3. main.py
cat > main.py <<'EOF'
from fastapi import FastAPI, UploadFile, File
from retriever import query_index
from pydantic import BaseModel

import shutil
import os

app = FastAPI()

class RAGQuery(BaseModel):
    query: str
    top_k: int = 3

@app.post("/rag/query")
async def rag_query(payload: RAGQuery):
    answer = query_index(payload.query, top_k=payload.top_k)
    return {"context": str(answer)}

UPLOAD_DIR = "./documents"

@app.post("/rag/upload")
async def upload_file(file: UploadFile = File(...)):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "filename": file.filename}
EOF

# 4. Dockerfile
cat > Dockerfile <<'EOF'
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

echo "✅ RAG-Service vorbereitet unter ./rag-backend"

echo "📦 Baue Docker-Image..."
docker build -t rag-backend .

echo "🚀 Starte RAG-Service auf Port 8000..."
docker run -d --name rag-backend -p 8000:8000 -v $(pwd)/documents:/app/documents -v $(pwd)/storage:/app/storage rag-backend

echo "🌐 RAG API erreichbar unter: http://localhost:8000/rag/query"
