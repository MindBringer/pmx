#!/bin/bash
set -e

APP_NAME="ai-ui"
TARGET_DIR="/var/www/$APP_NAME"

echo "📁 Kopiere Web-UI nach $TARGET_DIR"
sudo mkdir -p "$TARGET_DIR"
sudo cp -r ./* "$TARGET_DIR/"
sudo chown -R www-data:www-data "$TARGET_DIR"

echo "✅ Web-UI wurde in $TARGET_DIR bereitgestellt."
echo "📌 Ergänze jetzt deine NGINX-Konfiguration für Zugriff über Subdomain oder Pfad."
#location /ui/ {
#    root /var/www/;
#    index index.html;
#    try_files $uri $uri/ /ui/index.html;
#}