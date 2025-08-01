#!/bin/bash
set -e

echo "📦 System wird vorbereitet..."

# System aktualisieren und Pakete installieren
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git docker.io docker-compose

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
docker-compose up -d

# IP-Adresse ermitteln
IP=$(hostname -I | awk '{print $1}')

echo "✅ Setup abgeschlossen!"
echo "🔗 n8n erreichbar unter: http://$IP:5678"
