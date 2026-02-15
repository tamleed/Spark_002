#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/llm-switchboard}"

cd "${PROJECT_ROOT}"
docker compose -f docker/docker-compose.yml up -d redis

sudo cp systemd/llm-gateway.service /etc/systemd/system/llm-gateway.service
sudo cp systemd/llm-worker.service /etc/systemd/system/llm-worker.service
sudo cp systemd/jupyter.service /etc/systemd/system/jupyter.service

sudo systemctl daemon-reload
sudo systemctl enable --now llm-gateway.service
sudo systemctl enable --now llm-worker.service
sudo systemctl enable --now jupyter.service

echo "[OK] Services started"
