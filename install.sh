#!/bin/bash
set -e

echo "📦 System wird vorbereitet..."

# System aktualisieren und Pakete installieren
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git docker.io docker-buildx

# Docker Compose Plugin prüfen und ggf. verlinken (für Kompatibilität)
if ! docker compose version >/dev/null 2>&1; then
  echo "⚠️ Docker Compose Plugin fehlt oder veraltet!"
  echo "Bitte manuell prüfen: https://docs.docker.com/compose/install/"
  exit 1
fi

# Docker-Gruppe setzen
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
echo "🚀 Starte Container..."
docker compose up -d

# IP-Adresse ermitteln
IP=$(hostname -I | awk '{print $1}')

echo "✅ Setup abgeschlossen!"
echo "🔗 n8n erreichbar unter: http://$IP:${N8N_PORT:-5678}"

