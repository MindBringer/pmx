#!/bin/bash
set -e

echo "📦 Installiere RAG-Backend..."

# Verzeichnis anlegen
mkdir -p rag-backend/documents rag-backend/storage
cd rag-backend

# Beispiel-Dokument
echo "OAuth2 ist ein Autorisierungsprotokoll zur sicheren Delegation..." > documents/oauth.txt

echo "✅ RAG-Service vorbereitet unter ./rag-backend"

echo "📦 Baue Docker-Image..."
docker build -t rag-backend .

echo "🚀 Starte RAG-Service auf Port 8000..."
docker run -d --name rag-backend -p 8000:8000 -v $(pwd)/documents:/app/documents -v $(pwd)/storage:/app/storage rag-backend

echo "🌐 RAG API erreichbar unter: http://localhost:8000/rag/query"
