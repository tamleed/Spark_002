#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://127.0.0.1:8000}"
API_KEY="${GATEWAY_API_KEY:-}"
MODEL_A="${MODEL_A:-gpt-oss120}"
MODEL_B="${MODEL_B:-qwen3-30b}"

H=()
if [[ -n "$API_KEY" ]]; then
  H=(-H "X-API-Key: $API_KEY")
fi

curl -sf "${API_URL}/health"
curl -sf "${API_URL}/v1/models" "${H[@]}"

create_job() {
  local model="$1"
  local prompt="$2"
  curl -sf -X POST "${API_URL}/v1/chat/completions" "${H[@]}" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"${model}\",\"async\":true,\"messages\":[{\"role\":\"user\",\"content\":\"${prompt}\"}],\"max_tokens\":32}" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["job_id"])'
}

wait_job() {
  local id="$1"
  for _ in $(seq 1 120); do
    status=$(curl -sf "${API_URL}/jobs/${id}" "${H[@]}" | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])')
    if [[ "$status" =~ ^(succeeded|failed|cancelled)$ ]]; then
      echo "$status"
      return 0
    fi
    sleep 2
  done
  echo "timeout"
}

JOB1=$(create_job "$MODEL_A" "Say hello")
S1=$(wait_job "$JOB1")
echo "job1=${JOB1} status=${S1}"

JOB2=$(create_job "$MODEL_B" "Count to ten")
S2=$(wait_job "$JOB2")
echo "job2=${JOB2} status=${S2}"

curl -sf "${API_URL}/status" "${H[@]}"

LONG_JOB=$(create_job "$MODEL_B" "Write a very long detailed essay with many sections")
sleep 1
curl -sf -X POST "${API_URL}/jobs/${LONG_JOB}/cancel" "${H[@]}"
curl -sf "${API_URL}/jobs/${LONG_JOB}" "${H[@]}"

echo "[OK] smoke tests finished"
