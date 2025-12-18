# PMX Plattform – Übersicht, Betrieb & Persistenz

Diese README fasst alle aktiven Module, Container, Skripte und Schnittstellen von **MindBringer/pmx** zusammen. Ziel ist ein reproduzierbarer 2-VM-Stack (GPU + Services) mit klarer Datenhaltung und Backup-Strategie.

## 1) Architektur & Rollen
- **srv-ai01 (GPU-VM)**: ollama, vLLM, Audio-API (Transcribe/Diarize/Identify/Speakers).
- **srv-aisvc (Services-VM)**: RAG-Backend, Qdrant, n8n, optional statisches Frontend & Nginx/TLS.
- Gemeinsames Compose-File mit Profilen (`ai`, `ai-vllm`, `svc`) und einem gemeinsamen Netzwerk `ai-net` (kann über die VM-Grenze via Overlay/Bridge geführt werden).

**Kern-Ports**
- RAG-Backend: `8082` (typischerweise hinter Nginx unter `/rag/*`)
- Audio-API: `6080`
- Qdrant: `6333`
- ollama: `11434`
- vLLM (OpenAI-kompatibel): `8001` (Container-Port 8000)
- n8n: `5678`
- Nginx (Beispiel): `443`/`80`

## 2) Container & Profile (docker-compose.yml)
| Service | Profile | Ports (Host→Container) | Zweck | Persistenz |
| --- | --- | --- | --- | --- |
| `ollama` | `ai` | 11434:11434 | LLM/Embedding-Serving | `ollama-data`, `ollama-models` |
| `audio-api` | `ai`, `ai-vllm` | 6080:6080 | Whisper-Transcribe, Speaker Mgmt, Diarize/Identify | `rag_storage` (Speaker-Files), Jobs in `/data/jobs` (separat mounten, s.u.) |
| `vllm-allrounder` | `ai`, `ai-vllm` | 8001:8000 | OpenAI-kompatibles Gateway | `vllm-models`, `vllm-cache` |
| `qdrant` | `svc` | 6333:6333 | Vektor-DB (Dokumente & Speaker-Embeddings) | `qdrant_data` |
| `rag-backend` | `svc` | 8082:8082 | FastAPI RAG, Dokumenten-Parsing & Jobs | `rag_documents`, `rag_storage` |
| `n8n` | `svc` | ${N8N_PORT:-5678}:5678 | Automations/Workflows | `n8n-data` |

> **Hinweis:** Das Profil `ai-vllm` startet `audio-api` + `vllm-allrounder` ohne `ollama`. Die Profile sind so gedacht, dass jede VM nur ihr eigenes Profil fährt.

## 3) APIs & Endpunkte

### RAG-Backend (FastAPI, Basis `/rag` hinter Nginx)
Quellcode: `rag-backend/app/main.py` (+ Router). Kernfunktionen:
- `GET /rag/health` – Liveness.
- `POST /rag/index` – Datei-Uploads (multipart `files[]`, optionale `tags`) oder JSON (`documents`, `collection`). Auto-Tagging & Embeddings via Haystack, Speichern in Qdrant.
- `POST /rag/query` – Semantische Suche + Generierung. Filter per `tags_all`/`tags_any`, `top_k`, optional `collection`.
- `POST /rag/embed` – SentenceTransformer-Embeddings für Texte (Batching, optional Normalisierung, Modellwahl pro Request).
- `GET /rag/embed/env` – geladene Embedding-Konfiguration.
- `POST /rag/parse` – Dokument-Parsing (PDF, DOCX, ODT, XLSX, CSV, HTML, TXT, PPTX, EML) aus Upload oder `file_url`. Liefert normalisierte Sections + Text; `JOBS_DIR`-basiertes Async-Pendant per `BackgroundTasks`.
- `POST /rag/jobs` + `GET /rag/jobs/{id}/events|result` – leichter SSE-Jobstore für Langläufer (genutzt von n8n/Frontend für Progress-Streams).
- `POST /rag/qdrant/upsert`, `GET /rag/qdrant/collections`, `GET /rag/qdrant/health` – direkte Qdrant-Hilfs-API (Collection-Autocreate, Health, Übersicht).

### Audio-API (im `audio-api`-Container, gleicher Code wie im RAG-Backend)
Router liegen unter `rag-backend/app/routers`:
- **Transkription:** `POST /transcribe` (Sync, Multipart-`file`, optionale Whisper-Parameter), `POST /transcribe/async` (`file_url`, optional `callback_url`, Meta), `GET /transcribe/jobs/{id}` (Polling), `GET /transcribe/env` (Model/Device-Status). VAD, Chunking, Parameter Overrides pro Request; FFMPEG-gestütztes Reencode.
- **Diarization:** `POST /diarize` (Segmentierung), `POST /diarize/async`, `GET /diarize/jobs/{id}`. Nutzt Pyannote (`DIAR_AUTH_TOKEN` nötig).
- **Speaker Management:** `POST /speakers/enroll`, `GET /speakers/list`, `POST /speakers/delete`, `POST /speakers/clear`, `GET /speakers/env`. Embeddings in Qdrant-Collection `speakers`, Files unter `/app/storage/speakers`.
- **Speaker Identify:** `POST /identify` (Upload + optionale Segmente aus `/diarize`), `POST /identify/async`, `GET /identify/jobs/{id}`. Cosine-Matching gegen Qdrant oder lokales JSON-Fallback.

> Default-Parameter (z.B. `ASR_MODEL`, `DEVICE`, `SPEAKER_BACKEND`, `QDRANT_URL`, `SPEAKER_COLLECTION`) kommen aus Umgebungsvariablen; Jobs liegen in `JOBS_DIR` (Standard `/data/jobs` → eigenen Host-Pfad mounten, wenn dauerhaft benötigt).

### Weitere Komponenten
- **Frontend (`frontend/`, `install_www.sh`)**: Statisches UI, optional via Nginx unter `/ui/` aus `/var/www/ui` serviert.
- **Nginx**: Beispiel-Konfigs in `nginx_ai_local.sh`, `nginx_ai_intern.sh`, `nginx_ai_domain.sh` sowie TLS-Automatisierung `install_ssl.sh`. Typische Routen: `/rag/*` → `rag-backend`, `/rag/transcribe|speakers|identify|diarize/*` → Audio-API (GPU-VM), `/webhook/*` → n8n.

## 4) N8N-Workflows (`n8n-workflow/*.json`)
- **Main V3**: Webhook `POST /llm`, lädt/aktualisiert Memory, orchestriert Agentenlauf via Subworkflow `Agent Orchestrator V2`, unterstützt Sync/Async (Job-Streams über `/rag/jobs`).
- **Agent Orchestrator V2**: Mehr-Runden-Agents (Personas), ruft `RAG Router V3` für Retrieval/LLM-Aufrufe, kann Tools via `Tools Router` aufrufen, emittiert Events (`emit_event`) für Fortschritt.
- **RAG Router V3**: Routing auf unterschiedliche LLM-Provider (Ollama/vLLM/OpenAI/Groq/OpenRouter/Mistral/HF/Anthropic), optional Retrieval-Context via `/rag/query`, Token-Budget-Gating, Formatierung des Outputs.
- **Tools Router**: Standardisierte Tool-Ausführung (Google, interne SOA/DB Calls), Aggregation der Observations.
- **Transcribe and Summarize V2**: Webhook für Audio; ruft `/rag/transcribe`, optional `/diarize` & `/identify`, chunked Summaries über `RAG Router V3`, Embedding der Chunks/Summary.
- **Emit Event**: Hilfsflow zum Posten von Job-Events.

## 5) Setup & Betrieb

### Voraussetzungen
- Ubuntu Server 24.04 (empfohlen), Docker + Compose Plugin.
- Zwei VMs mit Connectivity (Beispiel): `srv-ai01` (GPU) 192.168.30.43, `srv-aisvc` (Services) 192.168.30.42.
- GPU-VM mit NVIDIA-Treibern + `nvidia-container-toolkit` (manuell ausführen, siehe Abschnitt "GPU vorbereiten").

### Storage vorbereiten
- **Empfohlen:** Dedizierte Disk nach `/docker` mounten. Skript `setup-storage.sh` kann Docker data-root und Projektpfade migrieren (`--mode data-root|projects|both`, optional Symlinks nach `/docker/projects/pmx`).
- Alternativ manuell: Datendisk formatieren + in `/etc/docker/daemon.json` `{"data-root":"/docker/docker-data"}` setzen, Projektpfade (`rag-backend/documents`, `rag-backend/storage`, Snapshots) auf dieselbe Disk verschieben/symlinken.

### Basissetup (beide VMs)
```bash
sudo apt update && sudo apt install -y curl git jq rsync ca-certificates gnupg lsb-release ffmpeg
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# ab- und wieder anmelden
```

### GPU vorbereiten (nur srv-ai01)
```bash
sudo apt install -y ubuntu-drivers-common
sudo ubuntu-drivers autoinstall && sudo reboot
# danach:
nvidia-smi
# NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### Repository & Umgebungsvariablen
```bash
git clone https://github.com/MindBringer/pmx /opt/pmx
cd /opt/pmx
cp -n .env.example .env
cp -n rag-backend/.env rag-backend/.env.example 2>/dev/null || true
# rag-backend/.env anpassen: API_KEY, OLLAMA_BASE_URL (GPU-VM), QDRANT_URL (Services-VM), SCORE_THRESHOLD, TOP_K, OPENAI_BASE_URL/KEY (für vLLM)
# N8N-Login: N8N_USER/N8N_PASS (Umgebungsvariablen oder .env)
```

### TLS / Nginx (Services-VM)
- Self-Signed/Let’s Encrypt via `install_ssl.sh` (erstellt Certs + Nginx-Site) oder manuell Zertifikate unter `/etc/ssl/selfsigned`/`/etc/letsencrypt` bereitstellen.
- Beispiel-Routing siehe `nginx_ai_intern.sh` (LAN) oder `nginx_ai_domain.sh` (FQDN). Wichtig: SSE-Location `/rag/jobs/` ohne Proxy-Buffering.

### Start der Container
- **GPU-VM:**
  ```bash
  docker compose --profile ai up -d          # ollama + audio-api
  # oder: docker compose --profile ai-vllm up -d   # audio-api + vLLM ohne ollama
  ```
- **Services-VM:**
  ```bash
  docker compose --profile svc up -d         # qdrant + rag-backend + n8n
  ```
- Modelle laden (GPU-VM):
  ```bash
  docker exec -it ollama sh -lc "ollama pull llama3"
  docker exec -it ollama sh -lc "ollama pull mxbai-embed-large"
  # vLLM: HF_TOKEN in .env setzen, Modell per ENV VLLM_MODEL_ALLROUNDER
  ```

### Manuelle Schritte, falls Skripte nicht alles abdecken
- **Frontend deployen:** `./install_www.sh` (kopiert `frontend/` nach `/var/www/ui`).
- **RAG Einzelaufbau ohne Compose:** `./install_rag.sh` (baut `rag-backend` lokal auf Port 8000; ggf. Port in `setup-storage.sh --rag-port` patchbar).
- **Nginx aufsetzen:** Falls Skripte nicht passen, eigene Site unter `/etc/nginx/sites-available/pmx` mit Proxy-Pfaden wie in Abschnitt 3 erstellen; Zertifikate manuell hinterlegen.
- **Persistente Job-Queues:** Für Audio-/Parse-Jobs `JOBS_DIR` als Host-Volume mounten (z. B. `- ./jobs:/data/jobs` im Compose Override), sonst gehen Job-States beim Container-Restart verloren.

## 6) Datenhaltung & Persistenz
- **Docker Volumes (Compose):**
  - `ollama-data`, `ollama-models`: Modelle & Cache von ollama (GPU-VM).
  - `vllm-models`, `vllm-cache`: vLLM Gewichte & HF-Cache (GPU-VM).
  - `rag_documents`: Upload-Originale; `rag_storage`: Chunks/Metadaten & Speaker-Files (Services-VM, wird auch vom `audio-api` genutzt).
  - `qdrant_data`: Qdrant-Datenbank (Services-VM).
  - `n8n-data`: n8n-Flowdaten & Credentials.
- **Bind-Mounts empfohlen:** Volumes auf Datendisk (`/docker/projects/pmx/...`) legen oder per `setup-storage.sh` symlinken.
- **JOBS_DIR:** Standard `/data/jobs` im Audio/Parse-Code; als eigenes Volume mounten, wenn Langläufer/Callbacks zuverlässig sein müssen.
- **Env/Secrets:** `.env`, `rag-backend/.env`, TLS-Keys, n8n-Credentials sicher außerhalb des Repos speichern und in Backups aufnehmen.

## 7) Backup-Strategie (Beispiele)
1. **Qdrant-Snapshots:**
   ```bash
   # Snapshot einer Collection
   docker exec qdrant curl -X POST http://localhost:6333/collections/pmx_docs/snapshots
   # Resultat liegt in /qdrant/snapshots – mit Volume sichern (s.u.)
   ```
2. **Volumes archivieren (restic/tar):**
   ```bash
   mkdir -p backups
   docker run --rm -v qdrant_data:/data -v $(pwd)/backups:/backup busybox \
     sh -c 'tar czf /backup/qdrant_$(date +%Y%m%d).tgz /data'
   docker run --rm -v rag_storage:/data -v $(pwd)/backups:/backup busybox \
     sh -c 'tar czf /backup/rag_storage_$(date +%Y%m%d).tgz /data'
   docker run --rm -v n8n-data:/data -v $(pwd)/backups:/backup busybox \
     sh -c 'tar czf /backup/n8n_$(date +%Y%m%d).tgz /data'
   docker run --rm -v ollama-models:/data -v $(pwd)/backups:/backup busybox \
     sh -c 'tar czf /backup/ollama_$(date +%Y%m%d).tgz /data'
   ```
3. **Configs & Workflows:** `.env`-Dateien, `n8n-workflow/*.json`, Nginx-Sites und Zertifikate separat sichern (z. B. git-Repo privat oder verschlüsseltes Vault).
4. **Offsite/Rotation:** Backups auf getrennte Storage (z. B. S3/MinIO mit Versionierung); Wiederherstellung testen (Volume-Restore in Test-Stack).

## 8) Betrieb & Checks
- Logs: `docker logs -f <service>`.
- Health:
  - `curl http://localhost:8082/health` (RAG-Backend)
  - `curl http://localhost:6333/healthz` (Qdrant)
  - `curl http://localhost:11434/api/tags` (ollama)
  - `curl http://localhost:6080/health` (Audio-API, falls Healthcheck aktiv)
  - `curl http://localhost:8001/v1/models` (vLLM)
- Updates: `git pull && docker compose --profile ai pull --no-parallel && docker compose --profile ai up -d` (entsprechend für `svc`).

## 9) Verzeichnis-Quickref
- `docker-compose.yml` – Profile & Volumes.
- `rag-backend/app/...` – FastAPI-Router für RAG, Audio, Qdrant, Jobs, Parsing, Embeddings.
- `n8n-workflow/*.json` – Exporte der Flows (siehe Abschnitt 4).
- `frontend/` – statische UI; Deployment via `install_www.sh`.
- `setup-storage.sh` – Storage-Migration & Symlink-Helfer.
- `nginx_ai_*.sh`, `install_ssl.sh` – Beispiel-Proxies & TLS.
- `install.sh`, `install_rag.sh` – Schnell-Installer (lokal), für produktiven Split ggf. manuell nach Abschnitt 5 anpassen.
