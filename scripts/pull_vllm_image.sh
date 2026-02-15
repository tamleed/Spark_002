#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/opt/llm-switchboard}"
MODELS_FILE="${MODELS_YAML_PATH:-${PROJECT_ROOT}/configs/models.yaml}"

IMAGES=$(python3 - <<PY
import yaml
from pathlib import Path
p=Path('${MODELS_FILE}')
data=yaml.safe_load(p.read_text())
imgs=sorted({m['backend']['image'] for m in data.get('models',[])})
print('\n'.join(imgs))
PY
)

if [[ -z "${IMAGES}" ]]; then
  echo "No images found in ${MODELS_FILE}" >&2
  exit 1
fi

while IFS= read -r image; do
  [[ -z "$image" ]] && continue
  echo "[INFO] Pulling $image"
  docker pull "$image"
done <<< "$IMAGES"

echo "[OK] vLLM images pulled"
