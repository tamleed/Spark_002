#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/opt/llm-switchboard"
PYTHON_BIN="${PYTHON_BIN:-python3}"
JUPYTER_VENV="/opt/jupyter-venv"

if ! command -v docker >/dev/null 2>&1; then
  echo "[INFO] Installing docker"
  sudo apt-get update
  sudo apt-get install -y docker.io docker-compose-plugin
  sudo systemctl enable --now docker
else
  echo "[INFO] docker already installed"
fi

if ! getent group docker >/dev/null 2>&1; then
  sudo groupadd docker
fi
sudo usermod -aG docker "${SUDO_USER:-$USER}" || true

if [[ ! -d "${PROJECT_ROOT}" ]]; then
  echo "[INFO] Copy project to ${PROJECT_ROOT} before running this script in production"
  sudo mkdir -p "${PROJECT_ROOT}"
fi

if [[ ! -d "${PROJECT_ROOT}/.venv" ]]; then
  sudo "${PYTHON_BIN}" -m venv "${PROJECT_ROOT}/.venv"
fi
sudo "${PROJECT_ROOT}/.venv/bin/pip" install --upgrade pip
sudo "${PROJECT_ROOT}/.venv/bin/pip" install -r "${PROJECT_ROOT}/requirements.txt"

if [[ ! -d "${JUPYTER_VENV}" ]]; then
  sudo "${PYTHON_BIN}" -m venv "${JUPYTER_VENV}"
fi
sudo "${JUPYTER_VENV}/bin/pip" install --upgrade pip jupyterlab

sudo mkdir -p /var/lib/huggingface /mnt/models /var/lock
sudo mkdir -p /home/"${SUDO_USER:-$USER}"/work

echo "[OK] Prerequisites installed"
