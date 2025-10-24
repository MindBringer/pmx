# PMX – Infrastruktur & RAG-Stack (aktualisiert)
Diese README spiegelt die aktuelle Struktur und Startanweisungen dieses Repos wider und klärt die **rein lokale** Ausführung der LLM-/RAG-Komponenten.
## Überblick
Enthalten sind Compose-Services für:
- **ollama** – lokaler Inferenzserver
- **vllm-allrounder** – OpenAI-kompatibles lokales Gateway (vLLM)
- **qdrant** – Vektorstore
- **rag-backend** – FastAPI + Haystack
- **n8n** – Orchestrierung/Automations
- **audio-api** – optionale Audio-Transkription
## Dienste & Ports
Aus `docker-compose.yml` erkannt:

```
{
  "images": {
    "ollama": "ollama/ollama",
    "audio-api": null,
    "vllm-allrounder": "vllm/vllm-openai:latest",
    "n8n": "n8nio/n8n",
    "qdrant": "qdrant/qdrant:latest",
    "rag-backend": null
  },
  "ports": {
    "ollama": [
      "11434:11434"
    ],
    "audio-api": [
      "6080:6080"
    ],
    "vllm-allrounder": [
      "8001:8000"
    ],
    "n8n": [
      "${N8N_PORT:-5678}:5678"
    ],
    "qdrant": [
      "6333:6333"
    ],
    "rag-backend": [
      "8082:8082"
    ]
  }
}
```
**Hinweis zur Erreichbarkeit innerhalb des Compose-Netzwerks:**
- Andere Container erreichen vLLM unter `http://vllm-allrounder:8000/v1`
- Host-Rechner erreicht vLLM unter `http://localhost:8001/v1`
## Lokale LLM-Nutzung sicherstellen
Der Generator im RAG-Backend ist als **OpenAI-kompatibles Interface** implementiert. Stelle sicher, dass er **lokal** spricht:

- `rag-backend/app/deps.py` → `OpenAIGenerator(api_base_url=OPENAI_BASE_URL, model=GENERATOR_MODEL, ...)`
- Setze Umgebungsvariablen für `rag-backend` so, dass sie auf vLLM zeigen:
  ```env
  OPENAI_BASE_URL=http://vllm-allrounder:8000/v1
  OPENAI_API_KEY=local-anything
  GENERATOR_MODEL=Qwen/Qwen2.5-7B-Instruct-GPTQ-Int4
  ```

> vLLM akzeptiert in der Regel beliebige API Keys (nur Format), solange `HF_TOKEN` die Modellgewichte beziehen darf.
## Quickstart
1. `.env` anlegen:
   ```bash
   cp .env.example .env
   cp .env.VM-AI.example .env.VM-AI
   # Passe Ports/Hostnamen an
   ```

2. Optional: Storage vorbereiten
   ```bash
   ./setup-storage.sh
   ```

3. Reverse Proxy / SSL nach Bedarf:
   ```bash
   ./nginx_ai_local.sh
   ./nginx_ai_intern.sh
   ./nginx_ai_domain.sh
   ./install_ssl.sh
   ```

4. Start:
   ```bash
   docker compose --profile ai up -d        # AI-VM (ollama, vllm)
   docker compose --profile svc up -d       # Service-VM (qdrant, rag-backend, n8n, audio-api)
   ```
## Healthchecks & Tests
- **RAG Backend:** `curl -s http://localhost:8082/health`
- **vLLM (OpenAI-kompatibel):**
  ```bash
  curl -s http://localhost:8001/v1/models | jq
  curl -s http://vllm-allrounder:8000/v1/models | jq   # aus Containern
  ```

- **End-to-End Test im rag-backend-Container:**
  ```bash
  docker exec -it rag-backend bash
  python - <<'PY'
  import os, openai
  client = openai.OpenAI(base_url=os.getenv("OPENAI_BASE_URL"), api_key=os.getenv("OPENAI_API_KEY"))
  print(client.models.list())
  PY
  ```
## Troubleshooting
- **Connection refused** beim Generieren → vLLM läuft nicht oder `OPENAI_BASE_URL` falsch. Korrekt: `http://vllm-allrounder:8000/v1`
- **Externe Calls vermeiden:** Keine `api.openai.com`-URLs setzen. Prüfe `env` des `rag-backend`:
  ```bash
  docker exec -it rag-backend env | sort | grep -E 'OPENAI|MODEL|VLLM'
  ```
- **Qdrant-Verbindung:** Aus `rag-backend`: `curl -s http://qdrant:6333/healthz`
## Projektstruktur (Top 2 Ebenen)
```
frontend/
n8n-workflow/
.git/
rag-backend/
meeting.m4a
.DS_Store
install_ssl.sh
install_rag.sh
install.sh
install_www.sh
readme.md
.dockerignore
nginx_ai_local.sh
ai.intern
docker-compose.yml
test.txt
setup-storage.sh
.env.VM-AI.example
cheatsheet.txt
.env.example
nginx_ai_intern.sh
nginx_ai_domain.sh
frontend/js/
frontend/index.html
frontend/.DS_Store
frontend/styles.css
frontend/app.js
frontend/js/ui/
frontend/js/utils/
frontend/js/.DS_Store
n8n-workflow/Tools Router.json
n8n-workflow/Agent Orchestrator V2.json
n8n-workflow/Main V3.json
n8n-workflow/Transcribe and Summarize V2.json
n8n-workflow/RAG Router V3.json
n8n-workflow/Emit Event.json
.git/objects/
.git/info/
.git/logs/
.git/hooks/
.git/refs/
.git/ORIG_HEAD
.git/config
.git/HEAD
.git/description
.git/index
.git/packed-refs
.git/COMMIT_EDITMSG
.git/FETCH_HEAD
.git/objects/61/
.git/objects/0d/
.git/objects/95/
.git/objects/59/
.git/objects/92/
.git/objects/0c/
.git/objects/66/
.git/objects/3e/
.git/objects/50/
.git/objects/68/
.git/objects/57/
.git/objects/3b/
.git/objects/6f/
.git/objects/03/
.git/objects/9b/
.git/objects/9e/
.git/objects/04/
.git/objects/6a/
.git/objects/32/
.git/objects/35/
.git/objects/69/
.git/objects/3c/
.git/objects/56/
.git/objects/51/
.git/objects/3d/
.git/objects/58/
.git/objects/67/
.git/objects/0b/
.git/objects/93/
.git/objects/94/
.git/objects/0e/
.git/objects/60/
.git/objects/34/
.git/objects/5a/
.git/objects/5f/
.git/objects/33/
.git/objects/05/
.git/objects/9d/
.git/objects/9c/
.git/objects/02/
.git/objects/a4/
.git/objects/a3/
.git/objects/b5/
.git/objects/b2/
.git/objects/d9/
.git/objects/ac/
.git/objects/ad/
.git/objects/bb/
.git/objects/d7/
.git/objects/d0/
.git/objects/be/
.git/objects/b3/
.git/objects/df/
.git/objects/da/
.git/objects/b4/
.git/objects/a2/
.git/objects/a5/
.git/objects/bd/
.git/objects/d1/
.git/objects/d6/
.git/objects/bc/
.git/objects/ae/
.git/objects/d8/
.git/objects/ab/
.git/objects/e5/
.git/objects/e2/
.git/objects/f4/
.git/objects/f3/
.git/objects/eb/
.git/objects/c7/
.git/objects/c0/
.git/objects/ee/
.git/objects/c9/
.git/objects/fc/
.git/objects/fd/
.git/objects/f2/
.git/objects/f5/
.git/objects/e3/
.git/objects/cf/
.git/objects/ca/
.git/objects/e4/
.git/objects/fe/
.git/objects/c8/
.git/objects/fb/
.git/objects/ed/
.git/objects/c1/
.git/objects/c6/
.git/objects/ec/
.git/objects/4e/
.git/objects/20/
.git/objects/18/
.git/objects/27/
.git/objects/4b/
.git/objects/pack/
.git/objects/11/
.git/objects/7d/
.git/objects/29/
.git/objects/7c/
.git/objects/16/
.git/objects/42/
.git/objects/89/
.git/objects/45/
.git/objects/1f/
.git/objects/73/
.git/objects/87/
.git/objects/80/
.git/objects/74/
.git/objects/1a/
.git/objects/28/
.git/objects/17/
.git/objects/7b/
.git/objects/8f/
.git/objects/8a/
.git/objects/7e/
.git/objects/10/
.git/objects/19/
.git/objects/4c/
.git/objects/26/
.git/objects/21/
.git/objects/4d/
.git/objects/75/
.git/objects/81/
.git/objects/86/
.git/objects/72/
.git/objects/44/
.git/objects/2a/
.git/objects/2f/
.git/objects/43/
.git/objects/88/
.git/objects/9f/
.git/objects/6b/
.git/objects/07/
.git/objects/38/
.git/objects/00/
.git/objects/6e/
.git/objects/9a/
.git/objects/36/
.git/objects/5c/
.git/objects/09/
.git/objects/5d/
.git/objects/31/
.git/objects/info/
.git/objects/91/
.git/objects/65/
.git/objects/62/
.git/objects/96/
.git/objects/3a/
.git/objects/54/
.git/objects/98/
.git/objects/53/
.git/objects/3f/
.git/objects/30/
.git/objects/5e/
.git/objects/5b/
.git/objects/37/
.git/objects/08/
.git/objects/6d/
.git/objects/01/
.git/objects/06/
.git/objects/6c/
.git/objects/39/
.git/objects/99/
.git/objects/52/
.git/objects/55/
.git/objects/97/
.git/objects/63/
.git/objects/0f/
.git/objects/0a/
.git/objects/64/
.git/objects/90/
.git/objects/bf/
.git/objects/d3/
.git/objects/d4/
.git/objects/ba/
.git/objects/a0/
.git/objects/a7/
.git/objects/b8/
.git/objects/b1/
.git/objects/dd/
.git/objects/dc/
.git/objects/b6/
.git/objects/a9/
.git/objects/d5/
.git/objects/d2/
.git/objects/aa/
.git/objects/af/
.git/objects/b7/
.git/objects/db/
.git/objects/a8/
.git/objects/de/
.git/objects/b0/
.git/objects/a6/
.git/objects/b9/
.git/objects/a1/
.git/objects/ef/
.git/objects/c3/
.git/objects/c4/
.git/objects/ea/
.git/objects/e1/
.git/objects/cd/
.git/objects/cc/
.git/objects/e6/
.git/objects/f9/
.git/objects/f0/
.git/objects/f7/
.git/objects/e8/
.git/objects/fa/
.git/objects/ff/
.git/objects/c5/
.git/objects/c2/
.git/objects/f6/
.git/objects/e9/
.git/objects/f1/
.git/objects/e7/
.git/objects/cb/
.git/objects/f8/
.git/objects/ce/
.git/objects/e0/
.git/objects/46/
.git/objects/2c/
.git/objects/79/
.git/objects/2d/
.git/objects/41/
.git/objects/83/
.git/objects/1b/
.git/objects/77/
.git/objects/48/
.git/objects/70/
.git/objects/1e/
.git/objects/84/
.git/objects/4a/
.git/objects/24/
.git/objects/23/
.git/objects/4f/
.git/objects/8d/
.git/objects/15/
.git/objects/12/
.git/objects/8c/
.git/objects/85/
.git/objects/1d/
.git/objects/71/
.git/objects/76/
.git/objects/1c/
.git/objects/82/
.git/objects/49/
.git/objects/40/
.git/objects/2e/
.git/objects/2b/
.git/objects/47/
.git/objects/78/
.git/objects/8b/
.git/objects/13/
.git/objects/7f/
.git/objects/7a/
.git/objects/14/
.git/objects/8e/
.git/objects/22/
.git/objects/25/
.git/info/exclude
.git/logs/refs/
.git/logs/HEAD
.git/hooks/commit-msg.sample
.git/hooks/pre-rebase.sample
.git/hooks/sendemail-validate.sample
.git/hooks/pre-commit.sample
.git/hooks/applypatch-msg.sample
.git/hooks/fsmonitor-watchman.sample
.git/hooks/pre-receive.sample
.git/hooks/prepare-commit-msg.sample
.git/hooks/post-update.sample
.git/hooks/pre-merge-commit.sample
.git/hooks/pre-applypatch.sample
.git/hooks/pre-push.sample
.git/hooks/update.sample
.git/hooks/push-to-checkout.sample
.git/refs/heads/
.git/refs/tags/
.git/refs/remotes/
rag-backend/app/
rag-backend/config/
rag-backend/scripts/
rag-backend/.DS_Store
rag-backend/requirements.txt
rag-backend/Dockerfile
rag-backend/README.md
rag-backend/requirements.audio.txt
rag-backend/Dockerfile.audio
rag-backend/.env.example
rag-backend/app/routers/
rag-backend/app/services/
rag-backend/app/deps.py
rag-backend/app/.DS_Store
rag-backend/app/embed.py
rag-backend/app/models.py
rag-backend/app/qdrant_api.py
rag-backend/app/__init__.py
rag-backend/app/jobs.py
rag-backend/app/parse_document.py
rag-backend/app/main.py
rag-backend/app/tagging.py
rag-backend/app/pipelines.py
rag-backend/config/settings.yaml
rag-backend/config/logging.ini
rag-backend/scripts/dev_run.sh
rag-backend/scripts/init_collections.py
```
