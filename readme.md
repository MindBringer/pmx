# PMX – Modularer KI-Stack mit HTTPS

Ein leichtgewichtiger, modularer KI-Stack mit Docker Compose, Ollama & n8n.

---

## 📦 Dienste

```
pmx/
├── ollama (http://localhost:11434)
├── n8n (https://ai.steinicke-gmbh.de)
├── install.sh
├── install_ssl.sh
└── n8n-workflow/prompting_wf.json
```

---

## 🛠 Installation

### 1. Basis-Installation

```bash
git clone https://github.com/MindBringer/pmx.git
cd pmx
cp .env.example .env
chmod +x install.sh
./install.sh
```

### 2. HTTPS aktivieren (Let's Encrypt mit Fallback auf Self-Signed)

```bash
chmod +x install_ssl.sh
sudo ./install_ssl.sh
```
> Voraussetzung: Domain `ai.domain.de` zeigt per DNS auf die öffentliche IP des Servers (A-Record).


---

## 🔐 Sicherheit & Cookie-Konfiguration

- Nach `install_ssl.sh` ist TLS aktiv.
- `.env` enthält automatisch `N8N_SECURE_COOKIE=true`, sodass Cookies korrekt über HTTPS gesetzt werden.

---

## 🧠 Beispielaufruf (curl)

```bash
curl -X POST https://ai.steinicke-gmbh.de/webhook/prompt \
  -H "Content-Type: application/json" \
  -u admin:supersecure \
  -d '{
    "prompt": "Was ist DevOps?",
    "model": "ollama"
  }'
```

---

## 📘 Modelle & API

| Modell    | Ziel-API                                    |
|-----------|---------------------------------------------|
| `ollama`  | http://ollama:11434/api/generate            |
| `openai`  | https://api.openai.com/v1/chat/completions  |

### Benötigte Parameter:
- `prompt` – Eingabetext
- `model` – `openai` oder `ollama`

---

## 🔁 Dienste steuern

```bash
docker compose ps          # Status
docker compose restart     # Neustart
./install_ssl.sh           # (Re-)Einrichtung TLS + Cookie
```

---

## 🌐 HTTPS-Domain vorbereiten

Bei deinem DNS-Provider:

| Typ | Name                  | Wert                |
|-----|-----------------------|---------------------|
| A   | ai.domain.de | <deine öffentliche IP> |

> 🔐 Port 80 & 443 müssen öffentlich erreichbar sein.

---

## 🔄 Erweiterbar für

- Weitere Modelle (über Ollama oder eigene Container)
- Frontends per Webhook/API
- Authentifizierung via OAuth/OpenID
- Logging mit Datenbank oder Dateisystem

---

## ✅ Fertig

Der Stack ist nach Installation über TLS verfügbar:

```
https://ai.domain.de
https://ai.local
```

Login: Benutzer/Passwort aus `.env`

curl --no-progress-meter --max-time 60 --retry 2 --retry-delay 3 \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Gib mir ein Beispiel für einen HTTP POST mit curl", "model": "ollama"}' \
  https://ai.local/webhook/llm

  SETUP frontend:
  bash /frontend/install.sh, nginx anpassen sudo nano /etc/nginx/sites-available/ai.local
  neustarten:
  sudo nginx -t && sudo systemctl reload nginx

setup RAG:
  bash install_rag.sh

  docker-compose ergänzen:
   rag-backend:
    build: ./rag-backend
    container_name: rag-backend
    ports:
      - "8000:8000"
    volumes:
      - ./rag-backend/documents:/app/documents
      - ./rag-backend/storage:/app/storage
    restart: unless-stopped
    networks:
      - ai-net

volumes:
  rag_documents:
  rag_storage:

Nach Installation aller install-scripte:

nginx 
sudo nano /etc/nginx/sites-enabled/ai.local/domain.de
CAT aus install_ssl.sh prüfen, aus frontend/install.sh ergänzen - local erstellen bei Bedarf!
starten:
sudo systemctl start nginx

cert für ai.local erstellen:
sudo mkdir -p /etc/ssl/selfsigned

sudo openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout /etc/ssl/selfsigned/ai.local.key \
  -out /etc/ssl/selfsigned/ai.local.crt \
  -subj "/CN=ai.local"
