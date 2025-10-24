# PMX – 2-VM KI-Stack (GPU + Services)

03:00.0 VGA compatible controller [0300]: NVIDIA Corporation GA106 [RTX A2000 12GB] [10de:2571] (rev a1)
03:00.1 Audio device [0403]: NVIDIA Corporation GA106 High Definition Audio Controller [10de:228e] (rev a1)

> **Ziel**: Stabiler, nachvollziehbarer Split des Stacks auf **zwei VMs**  
> **srv-ai01 (GPU)**: LLM-Serving & Audio (Transcribe, Speaker/Diarize)  
> **srv-aisvc (Services)**: RAG-Backend, Qdrant, n8n, Nginx (+SSL), Frontend

---

## Architektur (High-Level)

```
[Internet/LAN]
      │ 443/80 (TLS)
      ▼
[Nginx auf srv-aisvc]
  ├─ /rag/*            → RAG-Backend (srv-aisvc:8082)
  ├─ /rag/transcribe/* → audio-api (srv-ai01:6080)
  ├─ /rag/speakers/*   → audio-api (srv-ai01:6080)
  └─ /webhook/*        → n8n (srv-aisvc:5678)

[RAG-Backend]──┬──► Qdrant (srv-aisvc:6333)
               └──► Ollama (srv-ai01:11434)
```

**Hosts & IPs**  
- **srv-aisvc (Services-VM)**: `192.168.30.42`  
- **srv-ai01 (GPU-VM)**: `192.168.30.43`

**Kern-Ports**  
- **Nginx**: `443` (internes Zertifikat), `80` (→ 443 Redirect)  
- **RAG-Backend**: `8082` (Base-Pfad **`/rag`**)  
- **n8n**: `5678`  
- **Qdrant**: `6333`  
- **Ollama**: `11434`
- **vLLM**: `8000`  
- **Audio-API** (Transcribe/Speakers): `6080` *(optional: Diarize separat auf `6081`)*

---

## Repo-Struktur (relevant)

```
pmx/
├─ docker-compose.yml                # Profiles: ai / svc
├─ infra/nginx/conf.d/pmx.conf       # Site-Config (siehe unten)
├─ rag-backend/
│  ├─ Dockerfile                     # RAG-Backend (FastAPI)
│  ├─ Dockerfile.audio               # Audio-API Wrapper (verwendet transcribe/speakers)
│  ├─ .env                           # RAG-Backend-spez. Variablen
│  └─ app/
│     ├─ main.py                     # FastAPI RAG-Backend
│     ├─ transcribe.py               # Whisper + Speaker-Endpunkte (genutzt von audio-api)
│     ├─ speakers.py                 # Enrollment/Identify/Liste/Delete
│     ├─ services/
│     │  ├─ vad.py                   # VAD
│     │  └─ diarize.py               # (optional eigenständig nutzbar)
│     └─ ...
└─ frontend/ ...                     # (falls vorhanden)
```

> Die **Audio-API** baut **direkt** auf den bestehenden `transcribe.py`/`speakers.py` auf. Keine Logik-Duplizierung – nur ein schlanker FastAPI-Wrapper.

---

## Installation • Schritt für Schritt

### 0) Voraussetzungen

- Proxmox-Host mit RAID10 (12×600 GB HDD), 196 GB RAM, 12C/24T  
- Zwei VMs (Ubuntu Server 24.04 empfohlen):
  - **srv-ai01 (GPU)**: 16 vCPU, **128 GB RAM**, Disk **200 GB** + Datendisk für Modelle/Daten  
  - **srv-aisvc (Services)**: 6 vCPU, **32 GB RAM**, Disk **100 GB** + Datendisk für Daten  
- DNS/FQDN intern, z. B. `ai.intern` (Self-Signed ok)

### 1) Basis-Setup in beiden VMs

```bash
sudo apt update
sudo apt install -y curl git jq rsync ca-certificates gnupg lsb-release ffmpeg
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# (ab- und wieder anmelden)
```

**Daten-Mount (empfohlen):**
- Datendisk in der VM nach **`/docker`** hängen (UUID, `noatime`).
- Docker-Root und Projektpfade dorthin auslagern (z. B. via deinem `setup-storage.sh` – **A+B**).

### 2) GPU-VM (srv-ai01) – NVIDIA

```bash
sudo apt install -y ubuntu-drivers-common
sudo ubuntu-drivers autoinstall
sudo reboot

# danach:
nvidia-smi

# NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### 3) Repo deployen

**Beide VMs:**
```bash
git clone https://github.com/MindBringer/pmx /opt/pmx
cd /opt/pmx
```

**Services-VM (srv-aisvc):**
```bash
# .env für n8n & RAG anlegen/anpassen
cp rag-backend/.env rag-backend/.env.example 2>/dev/null || true
nano rag-backend/.env   # API_KEY, OLLAMA_BASE_URL, QDRANT_URL etc. (siehe unten)

# Nginx-Config ablegen
mkdir -p infra/nginx/conf.d
nano infra/nginx/conf.d/pmx.conf    # siehe Config unten
```

**GPU-VM (srv-ai01):**
- **Ollama** nutzt Standard-Port `11434`.  
- **Audio-API** (Transcribe/Speakers) läuft auf `6080` (basiert auf deinem `transcribe.py`/`speakers.py`).

---

## Konfiguration

### `.env` (Beispiele)

**`rag-backend/.env` (srv-aisvc):**
```
# RAG
RAG_BASE_PATH=/rag
API_KEY=CHANGE_ME

# Ollama (GPU-VM)
OLLAMA_BASE_URL=http://192.168.30.43:11434

# Qdrant (lokal auf srv-aisvc)
QDRANT_URL=http://qdrant:6333

# Optional: Score/TopK etc.
SCORE_THRESHOLD=0.65
TOP_K=5
```

**n8n (srv-aisvc, via Compose):**
```
N8N_PORT=5678
N8N_USER=<user>
N8N_PASS=<pass>
N8N_SECURE_COOKIE=true
```

**Audio-API (srv-ai01, via Compose-Env):**
```
DEVICE=cuda
ASR_MODEL=medium
ASR_COMPUTE_TYPE=float16
QDRANT_URL=http://192.168.30.42:6333
SPEAKER_COLLECTION=speakers
# QDRANT_API_KEY=... (falls aktiviert)
```

---

## Docker Compose • Profile

**Ein File für beide VMs.**  
Starte je VM **nur ihr Profil**:

- **GPU-VM:**
  ```bash
  docker compose --profile ai up -d
  ```
- **Services-VM:**
  ```bash
  docker compose --profile svc up -d
  ```

**Services pro Profil**

- `ai`: `ollama`, `audio-api` (Transcribe/Speakers, Port 6080)  
- `svc`: `qdrant`, `rag-backend` (8082), `n8n` (5678)

> Das `docker-compose.yml` enthält bereits die Profiles und `audio-api` (Build via `rag-backend/Dockerfile.audio`).

---

## Nginx-Site (srv-aisvc)

```nginx
server {
  listen 443 ssl;
  server_name ai.intern;

  ssl_certificate     /etc/ssl/selfsigned/ai.intern.crt;
  ssl_certificate_key /etc/ssl/selfsigned/ai.intern.key;
  ssl_protocols       TLSv1.2 TLSv1.3;
  client_max_body_size 200m;  # (erhöht)

  # /rag → /rag/
  location = /rag { return 301 /rag/; }

  # Jobs (SSE) → RAG lokal, Prefix NICHT strippen
  location ^~ /rag/jobs {
    proxy_pass         http://127.0.0.1:8082;
    proxy_http_version 1.1;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   Connection "";
    proxy_buffering    off;
    proxy_cache        off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
  }

  # Audio (GPU-VM) – Prefix STRIPPEN
  location ^~ /rag/transcribe/ {
    proxy_pass         http://192.168.30.43:6080/transcribe/;
    include            /etc/nginx/conf.d/proxy_common.conf;
  }
  location ^~ /rag/speakers/ {
    proxy_pass         http://192.168.30.43:6080/speakers/;
    include            /etc/nginx/conf.d/proxy_common.conf;
  }
  # Optional: separate Diarize-API (falls aktiviert)
  # location ^~ /rag/diarize/ {
  #   proxy_pass       http://192.168.30.43:6081/diarize/;
  #   include          /etc/nginx/conf.d/proxy_common.conf;
  # }

  # Restliche /rag/* → RAG lokal, Prefix STRIPPEN
  location ^~ /rag/ {
    proxy_pass         http://127.0.0.1:8082/;
    include            /etc/nginx/conf.d/proxy_common.conf;
  }

  # n8n Webhooks/UI
  location ^~ /webhook/ {
    proxy_pass         http://127.0.0.1:5678/webhook/;
    include            /etc/nginx/conf.d/proxy_common.conf;
  }
  location / {
    proxy_pass         http://127.0.0.1:5678;
    include            /etc/nginx/conf.d/proxy_common.conf;
  }
}

server {
  listen 80;
  server_name ai.local;
  return 301 https://$host$request_uri;
}
```

**`proxy_common.conf`** (Empfehlung)
```nginx
proxy_http_version 1.1;
proxy_set_header Host              $host;
proxy_set_header X-Real-IP         $remote_addr;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Upgrade           $http_upgrade;
proxy_set_header Connection        "upgrade";
proxy_read_timeout 600s;
proxy_connect_timeout 600s;
proxy_send_timeout 600s;
```

---

## Funktionen (Kurzüberblick)

- **Nginx**  
  Reverse Proxy (TLS), trennt sauber zwischen Routen:  
  `/rag/*` → RAG-Backend, `/rag/transcribe|speakers/*` → **GPU-Audio-API**, `/webhook/*` → n8n.

- **Frontend**  
  (Falls im Repo genutzt) Statisches UI unter `/ui/` servierbar; ansonsten Frontend-App kann gegen `/rag/*` sprechen.

- **RAG-Backend (FastAPI, Port 8082)**  
  - **`/rag/health`**  
  - **`/rag/index`**: Dokument-Upload + Ingestion (Chunking, Embedding, Tagging)  
  - **`/rag/query`**: Retrieval + Generation (Ollama) mit Tag-Filtern  
  - **`/rag/tags`**, **`/rag/docs/{id}/tags`**  
  - spricht mit **Qdrant** (Vectorstore) & **Ollama** (LLM/Embeddings)

- **n8n (5678)**  
  Automationen, Webhooks, Orchestrierung (z. B. Audio-Pipelines, Backups, Monitoring Hooks).

- **Audio-API (GPU, Port 6080)**  
  - **`/transcribe`**: ASR (faster-whisper/CTranslate2, CUDA)  
  - **`/speakers/*`**: Enrollment/Liste/Identify/Delete (Qdrant als Embedding-Store)  
  - Optional: **`/diarize`** (separat aktivierbar), wenn `services/diarize.py` als eigene API gefahren wird.

- **Qdrant (6333)**  
  Vektordatenbank (Dokument-Chunks, Speaker-Embeddings).

---

## Deployment

**GPU-VM:**
```bash
cd /opt/pmx
docker compose --profile ai-vllm build
docker compose --profile ai-vllm up -d
```

**Services-VM:**
```bash
cd /opt/pmx
docker compose --profile svc build
docker compose --profile svc up -d

# Nginx neu laden
sudo nginx -t && sudo systemctl reload nginx
```

---
**Modelle in Ollama laden (im Container)**
```bash
# Zentralen Ollama-Container verwenden
docker exec -it ollama sh -lc "ollama pull llama3"              # 8B instruct
docker exec -it ollama sh -lc "ollama pull mxbai-embed-large"   # Embeddings
docker exec -it ollama sh -lc "ollama pull mistral"             # LLM
docker exec -it ollama sh -lc "ollama list"


## Schnelltests

```bash
# RAG-Health
curl -fsS https://ai.intern/rag/health

# Tags
curl -fsS https://ai.intern/rag/tags

# Transcribe (Beispiel: Multipart Upload)
curl -fsS -X POST https://ai.intern/rag/transcribe \
  -F "file=@/path/to/audio.wav"

# Speaker Liste
curl -fsS https://ai.intern/rag/speakers/list

# Speaker Enroll (Beispiel)
curl -fsS -X POST https://ai.intern/rag/speakers/enroll \
  -F "name=Jan" -F "file=@/path/to/jan.wav"
```

> Die genauen Felder/Parameter richten sich nach deinen bestehenden `transcribe.py`/`speakers.py`. Oben sind gängige Defaults (Multipart `file=@...`, `name=...`).

---

## Datenhaltung & Backups

**Volumes (Standard-Compose):**
- **Ollama**: `ollama-data`, `ollama-models` (`/root/.ollama`) – **GPU-VM**
- **RAG**: `./rag-backend/documents`, `./rag-backend/storage` – **Services-VM**
- **Qdrant**: `qdrant_data` – **Services-VM**
- **n8n**: `n8n-data` – **Services-VM**

**Empfehlungen**
- Alle o. g. Pfade auf **dedizierte Datendisk** (VM-intern) legen, z. B. `/docker/projects/pmx/...` (Symlink-Variante ok).  
- Off-host Backup (restic/borg), zusätzlich Qdrant-Snapshots.

---

## Betrieb

- **Logs**: `docker logs -f <service>`  
- **Update**:
  ```bash
  git pull
  docker compose --profile ai pull --no-parallel && docker compose --profile ai up -d
  docker compose --profile svc pull --no-parallel && docker compose --profile svc up -d
  ```
- **Health**:  
  - RAG: `/rag/health`  
  - Ollama: `curl http://192.168.30.43:11434/api/tags`  
  - Audio-API: `curl http://192.168.30.43:6080/health` *(falls implementiert)*

---

## Security

- Nur **srv-aisvc** exponiert 443/80 nach außen.  
- **srv-ai01**-Dienste (11434/6080/6081) nur innerhalb des LAN erlauben.  
- API-Key (RAG) für Index/teure Endpunkte verwenden.  
- CORS nur so weit wie nötig.

---

## Troubleshooting

- **`/rag/transcribe` 502** → Läuft `audio-api` auf srv-ai01? Firewall zwischen VMs?  
- **Speaker-Identify leer** → Qdrant-URL/API-Key prüfen; Collection-Name (`SPEAKER_COLLECTION`) konsistent?  
- **RAG 404 auf `/rag/*`** → Nginx-Location-Reihenfolge prüfen; `proxy_pass` mit/ohne Slash beachten.  
- **GPU wird nicht genutzt** → `nvidia-smi` im Container testen; `device_requests` & `NVIDIA_VISIBLE_DEVICES` prüfen.

---

## Roadmap / Optional

- **Separate Diarize-API** (Port 6081) mit `services/diarize.py` aktivieren.  
- **Ingest-Worker** (z. B. Celery/RQ) für lange Index-Jobs.  
- **Monitoring**: Prometheus + Grafana + DCGM-Exporter (GPU-Metriken).

---

## Fehlende Details?

Wenn du bestätigst,
- ob **`rag-backend/Dockerfile.audio`** bereits im Repo liegt (oder geliefert werden soll), und
- welche **genauen Parameter** `transcribe`/`speakers` heute erwarten,

ergänzen wir die README direkt mit **API-Schemas (Request/Response)** und **konkreten cURL-Beispielen** aus deinem Stand.
