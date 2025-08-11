# PMX – Modularer KI‑Stack mit RAG (Haystack 2), n8n, Ollama & Proxy

Dieses Repository stellt einen produktionsnahen, schlanken KI‑Stack bereit:
- **Ollama** für lokale LLMs (z. B. *llama3*) und Embeddings.
- **n8n** für Automatisierung & Webhooks.
- **RAG‑Backend (Haystack 2)** mit **Qdrant** als Vektorspeicher und **Tag‑System**.
- **Reverse‑Proxy (nginx)** für TLS/HTTPS und Routing der Pfade (`/`, `/webhook/*`, `/rag/*`).
- **Frontend** (einfache UI) als Einstiegspunkt; sendet Prompts an n8n.

> Zielgruppe: technisch affine Anwender ohne tieferes Linux/Docker/ML‑Know‑how.  
> Systemvoraussetzungen: Ubuntu LTS, Docker Engine + Docker Compose v2.

---

## 1. Verzeichnis‑Überblick

```
pmx/
├─ install.sh               # Basis‑Setup: Docker installieren, .env erzeugen, Stack starten
├─ install_ssl.sh           # nginx + self‑signed Zertifikate (Domain/IP) einrichten
├─ install_rag.sh           # RAG‑Ordner vorbereiten (Dokumente/Storage, Beispiel)
├─ docker-compose.yml       # Zentrale Compose‑Datei (alle Services)
├─ .env.example             # Basis‑ENV (u. a. n8n)
├─ frontend/                # Minimal‑UI (index.html + script.js), spricht /webhook/llm
├─ n8n-workflow/Prompting.json  # Beispiel‑Workflow (Webhook)
├─ nginx_ai_domain.sh       # nginx‑Site für Domain (TLS, Routing)
├─ nginx_ai_local.sh        # nginx‑Site für lokale TLS‑Tests (self‑signed)
└─ rag-backend/
   ├─ Dockerfile
   ├─ requirements.txt
   ├─ .env.example          # ENV des RAG‑Backends
   └─ app/…                 # FastAPI + Haystack Pipelines
```

---

## 2. Architektur & Ports

```
[ Browser / Frontend ]
        |  / (Proxy)            /webhook/*                /rag/*
        v                      v                          v
+-----------------+    +-------------------+     +---------------------+
|   nginx (TLS)   | -> |      n8n          |     |   RAG-Backend       |
| :443 -> :5678   |    | :5678 (HTTP API)  |     | :8082 (FastAPI)     |
| :443 -> :8082   |    +-------------------+     +---------------------+
+--------+--------+               |                       |
         |                        | HTTP                  | HTTP
         |                        v                       v
         |                 +-------------+         +---------------+
         |                 |   Ollama    |         |    Qdrant     |
         |                 | :11434      |         | :6333         |
         |                 +-------------+         +---------------+
         |                        ^  ^
         |                        |  | Embeddings + Generation
         +------------------------+--+  (Modelle in /root/.ollama)
```

**Standard‑Ports (Host):**
- Proxy/HTTPS: **:443** (optional `:80` für Redirect)
- n8n: **:5678**
- RAG‑Backend (FastAPI): **:8082**
- Ollama API: **:11434**
- Qdrant: intern auf **:6333** (Host‑Mapping optional)

> Hinweis: In den nginx‑Skripten ist `/rag/` aktuell auf **`http://localhost:8000/`** geroutet.  
> Das neue RAG‑Backend lauscht **auf `:8082`** → **Proxy‑Ziel auf 8082 ändern** (siehe Kapitel 8 „Bekannte Abweichungen“).

---

## 3. Schnellstart

### 3.1 Basis‑Installation
```bash
# System vorbereiten (Docker/Compose, .env aus Vorlage, Stack starten)
./install.sh
```

Wenn Docker bereits vorhanden ist:
```bash
cp -n .env.example .env
docker network ls | grep -q ai-net || docker network create ai-net
docker compose up -d
```

### 3.2 Modelle in Ollama laden (im Container)
```bash
# Zentralen Ollama-Container verwenden
docker exec -it ollama sh -lc "ollama pull llama3"              # 8B instruct
docker exec -it ollama sh -lc "ollama pull mxbai-embed-large"   # Embeddings
docker exec -it ollama sh -lc "ollama pull mistral"             # LLM
docker exec -it ollama sh -lc "ollama list"
```

> `llama3:8b-instruct` ist **kein** gültiger Tag – verwende **`llama3`**.

### 3.3 RAG‑Backend konfigurieren
```bash
cp rag-backend/.env.example rag-backend/.env
# Passe bei Bedarf an:
#   OLLAMA_BASE_URL=http://ollama:11434
#   QDRANT_URL=http://qdrant:6333
#   LLM_MODEL=llama3
#   GENERATOR_MODEL=llama3
#   EMBED_MODEL=mxbai-embed-large
#   API_KEY=<setze-einen-schluessel>
```

### 3.4 Dienste starten/aktualisieren
```bash
# gesamten Stack
docker compose up -d --build

# nur RAG-Backend neu bauen & starten
docker compose build rag-backend --no-cache
docker compose up -d rag-backend
```

---

## 4. Frontend (UI)

- Dateien unter `frontend/` (statisch).  
- `script.js` sendet Prompts per **POST** an den **n8n‑Webhook** `/webhook/llm`.  
- Bereitstellung via Proxy (`/` → n8n:5678) oder separat (z. B. als statisches Hosting).

**Probe:** Browser auf `https://<deine-domain>/` öffnen → Eingabeformular testen.  
*(Ohne Proxy: `http://<server-ip>:5678`)*

---

## 5. n8n (Automatisierung)

- Standard‑Port: **5678**
- Beispiel‑Workflow: `n8n-workflow/Prompting.json`  
- Frontend ruft `POST /webhook/llm` auf (n8n muss den entsprechenden Webhook‑Trigger enthalten).

**Beispiele (CLI):**
```bash
# Webhook manuell testen (n8n)
curl -X POST http://localhost:5678/webhook/llm \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Sag Hallo", "model":"llama3"}'
```

---

## 6. RAG‑Backend (Haystack 2)

- Service‑Port: **8082**
- **Base‑Pfad:** `/rag` (z. B. `http://localhost:8082/rag/health`)
- nutzt **Ollama** (Generierung + Embeddings) und **Qdrant** (Vektorspeicher)
- **Tag‑System**: Auto‑Tags pro Chunk, manuell änderbar

**Endpoints:**
- `GET  /rag/health` → `{"status":"ok"}`
- `POST /rag/index`  (Form‑Upload `files[]`; optional JSON‑Feld `payload={"tags":[...]}`)  
  ↳ indexiert PDF/MD/HTML/TXT, Auto‑Tagging via Llama 3
- `POST /rag/query`  (JSON: `{ query, top_k?, tags_any?, tags_all?, with_sources? }`)
- `GET  /rag/tags`    → Aggregation aller Tags
- `PATCH /rag/docs/{id}/tags` → `{ add?, remove? }`

**Beispiele (CLI):**
```bash
# Health
curl -fsS http://localhost:8082/rag/health

# Indexierung (eine Datei, plus Default-Tags)
curl -H "x-api-key: $API_KEY" \
     -F "files=@README.md" \
     -F 'payload={"tags":["demo","policy"]}' \
     http://localhost:8082/rag/index

# Abfrage mit Tag-Filter
curl -H "x-api-key: $API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"query":"Was ist OAuth2?","tags_any":["demo"]}' \
     http://localhost:8082/rag/query | jq .

# Tags anzeigen
curl -H "x-api-key: $API_KEY" http://localhost:8082/rag/tags | jq .
```

---

## 7. Reverse‑Proxy (nginx)

Zwei Skripte helfen bei der Einrichtung von nginx‑Sites:
- `nginx_ai_domain.sh` – für **Domain** (self‑signed Zertifikat + Site‑File)
- `nginx_ai_local.sh` – für **lokale** TLS‑Tests (Hostname `ai.local`)

**Routing (empfohlen):**
- `/` und `/webhook/*` → **n8n** (**:5678**)
- `/rag/*` → **RAG‑Backend** (**:8082**)

> In den Skripten ist `/rag/` derzeit noch auf **8000** gesetzt → **auf 8082 ändern**.

---

## 8. Bekannte Abweichungen & Konsistenz‑Checks (wichtig)

### ❗ Proxy‑Ziel für `/rag/` falsch (8000 statt 8082)
- In `nginx_ai_domain.sh` und `nginx_ai_local.sh` zeigt `location /rag/ { proxy_pass http://localhost:8000/; }`
- **Fix:** auf `http://localhost:8082/` ändern und `sudo systemctl reload nginx`.

### ❗ „Zweiter“ Ollama‑Service (historisch)
- Falls `ollama-llama3` noch konfiguriert ist: entfernen oder beide auf **dasselbe** Models‑Volume `/root/.ollama` legen.
- **Empfehlung:** genau **einen** zentralen `ollama` betreiben.

### ❗ Netzwerk‑Definition
- Compose nutzt `ai-net`. Wenn du das Netz **manuell** erzeugst, setze in `docker-compose.yml`:
  ```yaml
  networks:
    ai-net:
      external: true
  ```
  oder lass Compose das Netz verwalten (ohne `external: true`).

### ❗ RAG‑README mit altem Modell‑Tag
- In `rag-backend/README.md` steht noch `ollama pull llama3:8b-instruct` → **ersetzen durch `ollama pull llama3`**.

### ❗ Python‑Abhängigkeiten
- Sichergestellt: `pydantic>=2.9,<3`, `haystack-ai>=2.16.1,<3`, `ollama-haystack==4.1.0`.
- Wenn Builds scheitern: `docker system prune -af --volumes` und `docker buildx prune -af`.

### ❗ .env‑Swapdatei
- Meldung „Bad lock file … `..env.swp`“ → Editor‑Swap löschen: `rm -f rag-backend/..env.swp`.

### ❗ Build‑Kontext & Pfade
- In der zentralen Compose:  
  ```yaml
  build:
    context: ./rag-backend
    dockerfile: Dockerfile
  env_file:
    - ./rag-backend/.env
  ```
  **Kein** doppeltes `rag-backend/rag-backend` angeben.

### ❗ Auto‑Start und Persistenz
- `restart: unless-stopped` für alle Services.
- Volumes für Persistenz prüfen: `ollama-data` (Modelle), `n8n-data`, `qdrant_data`, `rag_documents`, `rag_storage`.

---

## 9. Betrieb & Wartung (Kurzreferenz)

```bash
# Status
docker compose ps
docker compose logs -f rag-backend

# Neu bauen
docker compose build rag-backend --no-cache
docker compose up -d rag-backend

# Modelle prüfen
docker exec -it ollama sh -lc "ollama list"

# Qdrant erreichbar?
docker exec -it rag-backend curl -fsS http://qdrant:6333/ | jq .

# Healthchecks
curl -fsS http://localhost:8082/rag/health
curl -fsS http://localhost:5678/  | head -n 1
```

---

## 10. Deinstallation / Cleanup

```bash
# Container stoppen und entfernen
docker compose down

# Unbenutzte Ressourcen aufräumen (ACHTUNG: löscht Volumes!)
docker system prune -af --volumes
docker buildx prune -af || true
```

---

## 11. Häufige Fehlerbilder

- **`pull access denied for pmx/rag-backend`** → lokal bauen (`--build` oder `pull_policy: build`), `image:` zur Not entfernen.
- **`no space left on device`** → Build‑/Layer‑Caches leeren (siehe Cleanup).
- **`open Dockerfile: no such file or directory`** → `build.context`/`dockerfile` falsch (siehe Kapitel 8).
- **`Cannot install ... dependency conflict`** → `requirements.txt` aktualisieren (Pydantic ≥ 2.9; Haystack ≥ 2.16.1).

---

## 12. Sicherheit (Basics)

- Setze einen **API‑Key** für `/rag/*` in `rag-backend/.env` und halte `.env` **aus dem Repo**.
- TLS nur über den Proxy terminieren (Let’s Encrypt oder self‑signed mit `install_ssl.sh`).
- Keine Ports unnötig nach außen publishen; Kommunikation innerhalb des `ai-net` belassen.
