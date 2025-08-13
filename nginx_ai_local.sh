#!/bin/bash

set -e

NGINX_AVAILABLE="/etc/nginx/sites-available"
NGINX_ENABLED="/etc/nginx/sites-enabled"
CERT_PATH="/etc/ssl/selfsigned/ai.local.crt"
KEY_PATH="/etc/ssl/selfsigned/ai.local.key"

echo "📦 Erstelle Nginx-Konfiguration für ai.local..."

# Stelle sicher, dass Zertifikat vorhanden ist
if [[ ! -f "$CERT_PATH" || ! -f "$KEY_PATH" ]]; then
  echo "❌ Zertifikat nicht gefunden unter $CERT_PATH"
  exit 1
fi

# Konfigurationsdatei schreiben
cat <<EOF | sudo tee $NGINX_AVAILABLE/ai.local > /dev/null
  GNU nano 7.2                                                                    /etc/nginx/sites-available/ai.local                                                                             
  server {
  listen 443 ssl;
  server_name ai.local;

  ssl_certificate /etc/ssl/selfsigned/ai.local.crt;
  ssl_certificate_key /etc/ssl/selfsigned/ai.local.key;
  ssl_protocols TLSv1.2 TLSv1.3;

  client_max_body_size 50m;

  # exakt /rag -> mit Slash normalisieren
  location = /rag {
    return 301 /rag/;
  }

  # alles unter /rag/ -> RAG-Backend
  location ^~ /rag/ {
    proxy_pass http://localhost:8082/;  # /rag/index -> /index (Upstream Root)
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
  }

  # n8n UI als Fallback nur für /
  location / {
    proxy_pass http://localhost:5678;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
  }

  location /ui/ {
    root /var/www;
    index index.html;
    try_files $uri $uri/ /ui/index.html;
  }

  location /webhook/ {
    proxy_pass http://localhost:5678/webhook/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
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
  server_name ai.local;
  return 301 https://$host$request_uri;
}
EOF

# Symlink erstellen (falls nicht vorhanden)
if [[ ! -L "$NGINX_ENABLED/ai.local" ]]; then
  sudo ln -s "$NGINX_AVAILABLE/ai.local" "$NGINX_ENABLED/ai.local"
  echo "🔗 Symlink erstellt."
fi

# Nginx testen und neustarten
echo "🔄 Lade nginx neu..."
sudo nginx -t && sudo systemctl reload nginx

echo "✅ nginx für ai.local ist aktiv."