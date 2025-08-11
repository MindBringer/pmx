#!/bin/bash

set -e

DOMAIN="ai.domain.de"
NGINX_AVAILABLE="/etc/nginx/sites-available"
NGINX_ENABLED="/etc/nginx/sites-enabled"
CERT_PATH="/etc/ssl/selfsigned/$DOMAIN.crt"
KEY_PATH="/etc/ssl/selfsigned/$DOMAIN.key"

echo "📦 Erstelle Nginx-Konfiguration für $DOMAIN..."

# Prüfe ob Zertifikat vorhanden ist
if [[ ! -f "$CERT_PATH" || ! -f "$KEY_PATH" ]]; then
  echo "❌ Zertifikat nicht gefunden unter $CERT_PATH"
  exit 1
fi

# Konfigurationsdatei schreiben
cat <<EOF | sudo tee $NGINX_AVAILABLE/$DOMAIN > /dev/null
server {
  listen 443 ssl;
  server_name $DOMAIN;

  ssl_certificate $CERT_PATH;
  ssl_certificate_key $KEY_PATH;
  ssl_protocols TLSv1.2 TLSv1.3;

  location / {
    proxy_pass http://localhost:5678;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
  }

  location /ui/ {
    root /var/www;
    index index.html;
    try_files \$uri \$uri/ /ui/index.html;
  }

  location /webhook/ {
    proxy_pass http://localhost:5678/webhook/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
  }
  location /rag/ {
    proxy_pass http://localhost:8082/;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
  }

}

server {
  listen 80;
  server_name $DOMAIN;
  return 301 https://\$host\$request_uri;
}
EOF

# Symlink setzen (falls noch nicht vorhanden)
if [[ ! -L "$NGINX_ENABLED/$DOMAIN" ]]; then
  sudo ln -s "$NGINX_AVAILABLE/$DOMAIN" "$NGINX_ENABLED/$DOMAIN"
  echo "🔗 Symlink erstellt."
fi

# Nginx prüfen und neu laden
echo "🔄 Lade nginx neu..."
sudo nginx -t && sudo systemctl reload nginx

echo "✅ nginx für $DOMAIN ist aktiv."