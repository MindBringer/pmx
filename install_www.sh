#!/bin/bash
set -e

APP_NAME="ui"
TARGET_DIR="/var/www/$APP_NAME"

echo "📁 Kopiere Web-UI nach $TARGET_DIR"
sudo mkdir -p "$TARGET_DIR"
sudo cp -r ./frontend/* "$TARGET_DIR/"
sudo chown -R www-data:www-data "$TARGET_DIR"

echo "✅ Web-UI wurde in $TARGET_DIR bereitgestellt."
echo "📌 Ergänze jetzt deine NGINX-Konfiguration für Zugriff über Subdomain oder Pfad."
#location /ui/ {
#    root /var/www/;
#    index index.html;
#    try_files $uri $uri/ /ui/index.html;
#}
#location /webhook/ {
#    proxy_pass http://localhost:5678/webhook/;
#    proxy_set_header Host $host;
#    proxy_set_header X-Real-IP $remote_addr;
#    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#    proxy_set_header X-Forwarded-Proto $scheme;

    # Optional für WebSocket
#    proxy_http_version 1.1;
#    proxy_set_header Upgrade $http_upgrade;
#    proxy_set_header Connection "upgrade";

    # 👇 Timeout-Werte erhöhen
#    proxy_read_timeout 300;
#    proxy_connect_timeout 300;
#    proxy_send_timeout 300;
#}