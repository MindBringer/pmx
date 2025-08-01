#!/bin/bash
set -e

echo "📦 System wird vorbereitet..."

# System aktualisieren
sudo apt update && sudo apt upgrade -y

# Docker & Tools installieren, falls nicht vorhanden
if ! command -v docker >/dev/null 2>&1; then
  echo "🐳 Docker wird installiert..."
  sudo apt install -y ca-certificates curl gnupg lsb-release
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=\"$(dpkg --print-architecture)\" \
    signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt update
  sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  echo "✅ Docker ist bereits installiert"
fi

# Docker Compose (Plugin) prüfen
if ! docker compose version >/dev/null 2>&1; then
  echo "⚠️ Docker Compose Plugin fehlt! Installation..."
  sudo apt install -y docker-compose-plugin
else
  echo "✅ Docker Compose Plugin ist vorhanden"
fi

# Docker-Gruppe freischalten
sudo usermod -aG docker "$USER"

# Projektverzeichnis vorbereiten
cd ~
if [ ! -d "pmx" ]; then
  echo "📥 Klone Repository (optional)..."
  git clone https://github.com/MindBringer/pmx.git || mkdir pmx
fi
cd pmx

# .env vorbereiten
cp -n .env.example .env

# Docker-Stack starten
echo "🚀 Starte Container mit docker compose..."
docker compose up -d

# IP-Adresse ermitteln
IP=$(hostname -I | awk '{print $1}')

echo "✅ Setup abgeschlossen!"
echo "🔗 n8n erreichbar unter: http://$IP:${N8N_PORT:-5678}"

