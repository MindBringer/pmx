#!/bin/bash
set -e

DOMAIN="ai.steinicke-gmbh.de"
EMAIL="admin@$DOMAIN"
WEBROOT="/var/www/certbot"
CERT_DIR="/etc/letsencrypt/live/$DOMAIN"
IP=$(hostname -I | awk '{print $1}')
SELF_DIR="/etc/ssl/selfsigned"

# 1. Voraussetzungen installieren
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx openssl

# 2. Webroot vorbereiten
sudo mkdir -p $WEBROOT
sudo chown -R www-data:www-data $WEBROOT

# 3. Dummy Nginx-Konfiguration erstellen (für HTTP-Zugang)
NGINX_CONF="/etc/nginx/sites-available/$DOMAIN"
sudo tee $NGINX_CONF > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    root $WEBROOT;
    location ~ /.well-known/acme-challenge/ {
        allow all;
    }
}
EOF

sudo ln -sf $NGINX_CONF /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 4. Let's Encrypt Zertifikat holen
LE_SUCCESS=false
if sudo certbot certonly --webroot -w $WEBROOT -d $DOMAIN --email $EMAIL --agree-tos --non-interactive; then
    LE_SUCCESS=true
fi

# 5. Fallback: Self-signed Zertifikate erzeugen, wenn Let's Encrypt fehlschlägt
if [ "$LE_SUCCESS" = false ]; then
    echo "⚠️ Let's Encrypt fehlgeschlagen – erstelle Self-Signed Zertifikate"
    CERT_DIR="$SELF_DIR/$DOMAIN"
    sudo mkdir -p "$CERT_DIR"
    sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$CERT_DIR/privkey.pem" \
        -out "$CERT_DIR/fullchain.pem" \
        -subj "/CN=$DOMAIN"

    # Zusätzliches Zertifikat für IP-Adresse
    IP_DIR="$SELF_DIR/$IP"
    sudo mkdir -p "$IP_DIR"
    sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$IP_DIR/privkey.pem" \
        -out "$IP_DIR/fullchain.pem" \
        -subj "/CN=$IP" \
        -addext "subjectAltName=IP:$IP"

    # Zusätzliche nginx-Config für Zugriff via IP
    NGINX_IP_CONF="/etc/nginx/sites-available/$IP"
    sudo tee $NGINX_IP_CONF > /dev/null <<EOC
server {
    listen 443 ssl;
    server_name $IP;

    ssl_certificate $IP_DIR/fullchain.pem;
    ssl_certificate_key $IP_DIR/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://localhost:5678;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOC
    sudo ln -sf $NGINX_IP_CONF /etc/nginx/sites-enabled/
fi

# 6. HTTPS-konforme Nginx-Proxy-Konfiguration für Domain erzeugen
sudo tee $NGINX_CONF > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name $DOMAIN;

    ssl_certificate $CERT_DIR/fullchain.pem;
    ssl_certificate_key $CERT_DIR/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://localhost:5678;

        # Standard-Header
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Wichtig für WebSocket-Support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

}
EOF

sudo nginx -t && sudo systemctl reload nginx

# 7. Zertifikatserneuerung als Cronjob einrichten (nur bei Let's Encrypt)
if [ "$LE_SUCCESS" = true ]; then
    sudo bash -c 'echo "0 3 * * * certbot renew --post-hook \"systemctl reload nginx\"" > /etc/cron.d/letsencrypt-renew'
fi

# 8. Optional: N8N_SECURE_COOKIE auf true setzen in .env
if grep -q "N8N_SECURE_COOKIE" .env; then
    sed -i "s/^N8N_SECURE_COOKIE=.*/N8N_SECURE_COOKIE=true/" .env
else
    echo "N8N_SECURE_COOKIE=true" >> .env
fi

# 9. Docker neu starten
docker compose down && docker compose up -d

echo "✅ SSL (Let's Encrypt oder Self-Signed + IP-Fallback) eingerichtet."
echo "🌐 Zugriff jetzt über: https://$DOMAIN oder https://$IP"
