# pmx RAG Backend (Haystack 2.x) with Tag System

FastAPI-basiertes RAG-Backend mit Haystack 2.x, Qdrant und Ollama.
Nutzt Llama 3 zum Auto-Tagging und zur Antwortgenerierung; Embeddings via Ollama-Embedding-Modell.
Alle Komponenten sind über ENV austauschbar.

## Quickstart

```bash
cd rag-backend
cp .env.example .env

# Modelle auf dem Host laden (Ollama)
ollama pull llama3
ollama pull mxbai-embed-large

# Build & Run
docker build -t pmx/rag-backend:latest .
docker compose -f docker-compose.rag.yml up -d
```

Healthcheck: `GET /rag/health`

## API

- `POST /rag/index`  (Form: files[]; optional payload JSON-Feld `tags`)
- `POST /rag/query`  (JSON: { query, top_k?, tags_any?, tags_all?, with_sources? })
- `GET  /rag/tags`   (Listet aggregierte Tags)
- `PATCH /rag/docs/{id}/tags` (add/remove)

**Auth:** `x-api-key: $API_KEY`

### Index
```bash
curl -H "x-api-key: $API_KEY"          -F "files=@/path/file.pdf"          -F 'payload={"tags":["policy","project-x"]}'          http://localhost:8082/rag/index
```

### Query
```bash
curl -H "x-api-key: $API_KEY"          -H "Content-Type: application/json"          -d '{"query":"Wie richte ich SSO ein?","tags_all":["policy"],"top_k":5}'          http://localhost:8082/rag/query
```

## Integration in pmx
- Service hängt im externen Docker-Netz `pmx-net`.
- Reverse-Proxy: Pfadpräfix `/rag` weiterleiten (TLS übernimmt pmx-Proxy).
- Qdrant muss im gleichen Netz erreichbar sein (`qdrant:6333`).

## Modelle tauschen
In `.env`:
- `GENERATOR_MODEL` für Antworten (z.B. `qwen2.5:14b-instruct`)
- `EMBED_MODEL` für Embeddings (z.B. `nomic-embed-text`)
- `LLM_MODEL` für Tagging
