#!/bin/bash
set -e

echo "📦 System wird vorbereitet..."

# System aktualisieren
sudo apt update && sudo apt upgrade -y

echo "🐳 Prüfe Docker und Docker Compose Plugin..."

# Docker-Repository hinzufügen (falls noch nicht vorhanden)
if ! apt-cache policy | grep -q "download.docker.com"; then
  echo "🔧 Füge offizielles Docker-Repository hinzu..."
  sudo apt install -y ca-certificates curl gnupg lsb-release
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt update
fi

# Docker installieren, falls noch nicht vorhanden
if ! command -v docker >/dev/null 2>&1; then
  echo "📥 Installiere Docker Engine..."
  sudo apt install -y docker-ce docker-ce-cli containerd.io
else
  echo "✅ Docker ist bereits installiert"
fi

# Konfliktvermeidung: Ubuntu-Version von docker-buildx entfernen
if dpkg -l | grep -q docker-buildx; then
  echo "⚠️ Entferne vorhandenes docker-buildx (Ubuntu-Version)..."
  sudo apt remove -y docker-buildx
fi

# Docker Compose & Buildx Plugin installieren
echo "📥 Installiere Compose & Buildx Plugin..."
sudo apt install -y docker-buildx-plugin docker-compose-plugin

# Docker Compose testen
if docker compose version >/dev/null 2>&1; then
  echo "✅ Docker Compose Plugin erfolgreich installiert"
else
  echo "❌ Fehler bei Installation des Compose Plugins"
  exit 1
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
