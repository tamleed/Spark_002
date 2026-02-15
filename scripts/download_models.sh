#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/llm-switchboard}"
MODELS_FILE="${MODELS_YAML_PATH:-${PROJECT_ROOT}/configs/models.yaml}"
HF_CACHE_DIR="${HF_HOME:-/var/lib/huggingface}"

python3 - <<PY
import os
from pathlib import Path
import yaml
from huggingface_hub import snapshot_download

models_file = Path('${MODELS_FILE}')
cfg = yaml.safe_load(models_file.read_text())
hf_token = os.getenv('HF_TOKEN')
cache_dir = '${HF_CACHE_DIR}'

for m in cfg.get('models', []):
    source = m.get('source', {})
    if source.get('type') != 'huggingface_repo':
        continue
    repo_id = source['value']
    print(f"[INFO] Downloading {repo_id}")
    snapshot_download(repo_id=repo_id, cache_dir=cache_dir, token=hf_token, resume_download=True)

print('[OK] Model download complete')
PY
