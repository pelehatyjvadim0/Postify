#!/usr/bin/env bash
set -euo pipefail
cd /opt/autoposttg-next
exec 9>/run/lock/autoposttg-cert-renew.lock
flock -n 9 || exit 0
docker run --rm --network host \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot:v5.4.0 renew --cert-name autoposttg-ip \
  --webroot --webroot-path /var/www/certbot --quiet "$@"
docker compose -p autoposttg-v2 -f compose.yaml -f compose.production.yaml exec -T nginx nginx -s reload
