#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REMOTE_HOST="${ZHIKU_REMOTE_HOST:-82.156.187.35}"
REMOTE_USER="${ZHIKU_REMOTE_USER:-ubuntu}"
REMOTE_DIR="${ZHIKU_REMOTE_DIR:-/opt/zhiku-dashboard}"
ARCHIVE="/tmp/zhiku-dashboard-deploy-$(date +%Y%m%d%H%M%S).tar.gz"

cd "$ROOT_DIR"

tar --no-xattrs -czf "$ARCHIVE" -C deploy \
  backend/main.py \
  backend/requirements.txt \
  frontend/index.html \
  frontend/nginx.conf \
  docker-compose.yml \
  data/fault_codes_latest.json \
  data/oil_thermal_0105222512180008.json

scp "$ARCHIVE" "${REMOTE_USER}@${REMOTE_HOST}:/tmp/zhiku-dashboard-deploy.tar.gz"
ssh "${REMOTE_USER}@${REMOTE_HOST}" "cd '${REMOTE_DIR}' && tar xzf /tmp/zhiku-dashboard-deploy.tar.gz && rm /tmp/zhiku-dashboard-deploy.tar.gz && sudo docker compose build api && sudo docker compose up -d --force-recreate api web && sudo docker compose ps"
rm -f "$ARCHIVE"

echo "Deployed to http://${REMOTE_HOST}:8085"
