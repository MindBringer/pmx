#!/bin/bash

set -e

NGINX_AVAILABLE="/etc/nginx/sites-available"
NGINX_ENABLED="/etc/nginx/sites-enabled"
CERT_PATH="/etc/ssl/selfsigned/ai.intern.crt"
KEY_PATH="/etc/ssl/selfsigned/ai.intern.key"

echo "📦 Erstelle Nginx-Konfiguration für ai.intern..."

# Stelle sicher, dass Zertifikat vorhanden ist
if [[ ! -f "$CERT_PATH" || ! -f "$KEY_PATH" ]]; then
  echo "❌ Zertifikat nicht gefunden unter $CERT_PATH"
  exit 1
fi

# Konfigurationsdatei schreiben
cat <<EOF | sudo tee $NGINX_AVAILABLE/ai.intern > /dev/null
  GNU nano 7.2                                                                    /etc/nginx/sites-available/ai.intern                                                                             
server {
  listen 443 ssl;
  server_name ai.intern;

  ssl_certificate     /etc/ssl/selfsigned/ai.intern.crt;
  ssl_certificate_key /etc/ssl/selfsigned/ai.intern.key;
  ssl_protocols       TLSv1.2 TLSv1.3;

  client_max_body_size 200m;

  # 0) Nur /rag exakt -> /rag/ normalisieren (schadet nicht)
  location = /rag {
    return 301 /rag/;
  }

  # --- SPEAKERS API -> rag-backend ---
  location ^~ /speakers/ {
    proxy_pass         http://127.0.0.1:8082;   # Pfad unverändert durchreichen
    proxy_http_version 1.1;

    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;

    client_max_body_size 200m;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_connect_timeout 60s;
  }

  # 1) ALLE Job-Routen (/rag/jobs und /rag/jobs/...) — Präfix NICHT strippen
  #    => KEIN trailing slash bei proxy_pass
  location ^~ /rag/jobs {
    proxy_pass         http://127.0.0.1:8082;   # /rag bleibt erhalten
    proxy_http_version 1.1;

    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;

    # SSE/Streaming ok
    proxy_set_header   Connection         "";
    proxy_buffering    off;
    proxy_cache        off;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;

    # (Optional) CORS
    add_header Access-Control-Allow-Origin  *;
    add_header Access-Control-Allow-Methods 'GET, POST, PUT, PATCH, DELETE, OPTIONS' always;
    add_header Access-Control-Allow-Headers 'Content-Type, Authorization, X-API-Key' always;
    if ($request_method = OPTIONS) { add_header Content-Length 0; return 204; }
  }

  # 1.5) Audio-Services auf AI-VM (192.168.30.43)
  #      WICHTIG: trailing Slash + Zielpfad, damit /rag/transcribe/* → /transcribe/* umgeschrieben wird
  location ^~ /rag/transcribe/ {
    proxy_pass         http://192.168.30.43:6080/transcribe/;
    proxy_http_version 1.1;

    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;

    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;

    # CORS optional
    add_header Access-Control-Allow-Origin  *;
    add_header Access-Control-Allow-Methods 'GET, POST, PUT, PATCH, DELETE, OPTIONS';
    add_header Access-Control-Allow-Headers 'Content-Type, Authorization, X-API-Key';
    if ($request_method = OPTIONS) { add_header Content-Length 0; return 204; }
  }

  # exakt /rag/speakers  -> /speakers
  location = /rag/speakers {
    proxy_pass         http://127.0.0.1:8082/speakers;
    proxy_http_version 1.1;
    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;
  }

  # Präfix /rag/speakers/...  -> /speakers/...
  location ^~ /rag/speakers/ {
    rewrite ^/rag(/speakers/.*)$ $1 break;   # strippt /rag
    proxy_pass         http://127.0.0.1:8082;
    proxy_http_version 1.1;

    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;

    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_connect_timeout 60s;

    # CORS optional
    add_header Access-Control-Allow-Origin  *;
    add_header Access-Control-Allow-Methods 'GET, POST, PUT, PATCH, DELETE, OPTIONS';
    add_header Access-Control-Allow-Headers 'Content-Type, Authorization, X-API-Key';
    if ($request_method = OPTIONS) { add_header Content-Length 0; return 204; }
  }

  # (Optional) Separate Diarize-API auf AI-VM (falls aktiviert)
  location ^~ /rag/diarize/ {
    proxy_pass         http://192.168.30.43:6081/diarize/;
    proxy_http_version 1.1;

    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;

    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;

    # CORS optional
    add_header Access-Control-Allow-Origin  *;
    add_header Access-Control-Allow-Methods 'GET, POST, PUT, PATCH, DELETE, OPTIONS';
    add_header Access-Control-Allow-Headers 'Content-Type, Authorization, X-API-Key';
    if ($request_method = OPTIONS) { add_header Content-Length 0; return 204; }
  }

  # 1.6) vLLM-Instanzen auf AI-VM (192.168.30.43)

  # vLLM Allrounder → /v1/llm/...
  location ^~ /v1/llm/ {
    proxy_pass         http://192.168.30.43:8001/v1/;  # Achtung: trailing slash
    proxy_http_version 1.1;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
  }

  # vLLM LoRA-Basis → /v1/base/...
  location ^~ /v1/base/ {
    proxy_pass         http://192.168.30.43:8002/v1/;
    proxy_http_version 1.1;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
  }

  # 2) Restliche /rag/*-Routen (index, query, tags, docs, …):
  #    Präfix STRIPPEN: /rag/x -> /x
  #    => trailing slash bei proxy_pass!
  location ^~ /rag/ {
    proxy_pass         http://127.0.0.1:8082/;  # <— mit Slash, /rag wird entfernt
    proxy_http_version 1.1;

    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;

    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;

    # CORS optional
    add_header Access-Control-Allow-Origin  *;
    add_header Access-Control-Allow-Methods 'GET, POST, PUT, PATCH, DELETE, OPTIONS';
    add_header Access-Control-Allow-Headers 'Content-Type, Authorization, X-API-Key';
    if ($request_method = OPTIONS) { add_header Content-Length 0; return 204; }
  }

  # 3) Statisches UI unter /ui/
  location ^~ /ui/ {
    root  /var/www;
    index index.html;
    try_files $uri $uri/ /ui/index.html;
  }

  # 4) n8n Webhooks (falls genutzt)
  location ^~ /webhook/ {
    proxy_pass         http://127.0.0.1:5678/webhook/;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade            $http_upgrade;
    proxy_set_header   Connection         "upgrade";
    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
  }

  # 5) n8n UI als Fallback
  location / {
    proxy_pass         http://127.0.0.1:5678;
    proxy_http_version 1.1;
    proxy_set_header   Upgrade            $http_upgrade;
    proxy_set_header   Connection         "upgrade";
    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;
    proxy_read_timeout 600s;
    proxy_connect_timeout 600s;
    proxy_send_timeout 600s;
  }
}

server {
  listen 80;
  server_name ai.intern;
  return 301 https://$host$request_uri;
}
EOF

# Symlink erstellen (falls nicht vorhanden)
if [[ ! -L "$NGINX_ENABLED/ai.intern" ]]; then
  sudo ln -s "$NGINX_AVAILABLE/ai.intern" "$NGINX_ENABLED/ai.intern"
  echo "🔗 Symlink erstellt."
fi

# Nginx testen und neustarten
echo "🔄 Lade nginx neu..."
sudo nginx -t && sudo systemctl reload nginx

echo "✅ nginx für ai.intern ist aktiv."