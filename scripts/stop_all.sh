#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/llm-switchboard}"

sudo systemctl stop llm-gateway.service || true
sudo systemctl stop llm-worker.service || true
sudo systemctl stop jupyter.service || true

# optional: stop redis container
cd "${PROJECT_ROOT}"
docker compose -f docker/docker-compose.yml stop redis || true

# ensure inference backend is stopped as well
if docker ps -a --format '{{.Names}}' | grep -qx 'llm-switchboard-backend'; then
  docker rm -f llm-switchboard-backend || true
fi

echo "[OK] Services stopped"
