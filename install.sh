#!/usr/bin/env bash

set -e

# ==== LOGGING ====
LOGFILE="install-$(date +%Y%m%d-%H%M%S).log"
touch "$LOGFILE"

log() {
    echo -e "[INFO] $1" | tee -a "$LOGFILE"
}

warn() {
    echo -e "\033[1;33m[WARN] $1\033[0m" | tee -a "$LOGFILE"
}

error() {
    echo -e "\033[1;31m[ERROR] $1\033[0m" | tee -a "$LOGFILE"
    exit 1
}

trap 'error "Ein unerwarteter Fehler ist aufgetreten (Exit-Code: $?). Details siehe $LOGFILE."' ERR

log "===== Enterprise LLM Stack Installer ====="
log "Logfile: $LOGFILE"
log "Gestartet: $(date)"

# ==== NÜTZLICHE TOOLS INSTALLIEREN ====
log "Prüfe und installiere hilfreiche Tools und Abhängigkeiten..."
sudo apt-get update -y >> "$LOGFILE" 2>&1
sudo apt-get install -y git curl jq htop net-tools lsof apt-transport-https ca-certificates gnupg lsb-release >> "$LOGFILE" 2>&1

# ==== DOCKER CHECK ====
if ! command -v docker &>/dev/null; then
    log "Docker nicht gefunden. Starte Installation..."
    # Nach Docker-CE-Standard-Vorgehen
    sudo apt-get remove -y docker docker-engine docker.io containerd runc >> "$LOGFILE" 2>&1 || true
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -y >> "$LOGFILE" 2>&1
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >> "$LOGFILE" 2>&1
    log "Docker installiert!"
else
    log "Docker ist bereits installiert."
fi

# ==== DOCKER COMPOSE CHECK ====
if ! docker compose version &>/dev/null; then
    log "Docker Compose-Plugin fehlt. Installiere..."
    sudo apt-get install -y docker-compose-plugin >> "$LOGFILE" 2>&1
else
    log "Docker Compose-Plugin ist vorhanden."
fi

# ==== USER IN GRUPPE DOCKER ====
if groups $USER | grep -q docker; then
    log "User $USER ist bereits in der Gruppe 'docker'."
else
    log "Füge $USER zur Gruppe 'docker' hinzu."
    sudo usermod -aG docker $USER
    warn "Bitte einmal ab- und wieder anmelden, damit die Docker-Berechtigungen aktiv werden!"
fi

# ==== vLLM‑CPU‑IMAGE BAUEN ================================================
# Falls du eine NVIDIA‑GPU hast und CUDA nutzen willst, diesen Block überspringen
# und einfach das fertige CUDA‑Image in der compose lassen.
# ---------------------------------------------------------------------------
VLLM_VERSION="0.9.1"                       # gleiche Version wie Git‑Tag
VLLM_IMAGE="vllm/vllm-openai-cpu:${VLLM_VERSION}"

if ! docker image inspect "$VLLM_IMAGE" >/dev/null 2>&1; then
    log "Baue vLLM CPU‑Image ($VLLM_IMAGE) …"
    WORKDIR=$(mktemp -d)
    git clone --depth 1 --branch "v${VLLM_VERSION}" \
        https://github.com/vllm-project/vllm.git "$WORKDIR" >>"$LOGFILE" 2>&1
    docker build \
        -f docker/Dockerfile.cpu \
        --target vllm-openai \
        -t "$VLLM_IMAGE" \
        "$WORKDIR" >>"$LOGFILE" 2>&1
    rm -rf "$WORKDIR"
    log "vLLM CPU‑Image gebaut und getaggt als $VLLM_IMAGE"
else
    log "vLLM CPU‑Image $VLLM_IMAGE bereits vorhanden – überspringe Build."
fi
# ========================================================================== 

# ==== ENV FILE ====
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        log ".env aus .env.example erzeugt."
    else
        warn "Keine .env oder .env.example gefunden! Bitte .env manuell anlegen."
    fi
else
    log ".env bereits vorhanden."
fi

# ==== CONTAINER STOPPEN & CLEANUP ====
log "Prüfe laufende, alte oder fehlerhafte Container..."

if [ -f docker-compose.yml ]; then
    log "Stoppe laufende Compose-Container (falls vorhanden)..."
    docker compose down --remove-orphans >> "$LOGFILE" 2>&1 || warn "Konnte laufende Container nicht vollständig stoppen."
    log "Entferne nicht laufende, aber angelegte Container..."
    docker container prune -f >> "$LOGFILE" 2>&1
    log "Bereinige nicht verwendete Volumes (optional)..."
    docker volume prune -f >> "$LOGFILE" 2>&1
else
    warn "Keine docker-compose.yml gefunden! Abbruch."
    exit 1
fi

# ==== STACK STARTEN ====
log "Starte Stack: docker compose up -d ..."
docker compose up -d | tee -a "$LOGFILE"

# ==== STACK STATUS ====
log "Stack-Status:"
docker compose ps | tee -a "$LOGFILE"

log "Container-Logs siehst du mit: docker compose logs <servicename>"
log "Stack erreichbar:"
if grep -q ollama docker-compose.yml; then
    log "- Ollama:   http://localhost:11434"
fi
if grep -q vllm docker-compose.yml; then
    log "- vLLM:     http://localhost:8000"
fi
if grep -q gateway docker-compose.yml; then
    log "- Gateway:  http://localhost:8080"
fi

log "Fertig! Siehe $LOGFILE für Details und Fehlersuche."
