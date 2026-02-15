# LLM Switchboard for NVIDIA DGX Spark

Сервис внешнего доступа к нескольким LLM с гарантией: **одновременно активен только один inference backend**.

## Архитектура
- **Gateway**: FastAPI (`127.0.0.1:8000`), OpenAI-like API + async jobs.
- **Queue**: Redis + RQ.
- **Worker**: один процесс RQ (`admin`, `default`) — фактически обрабатывает 1 job одновременно.
- **Inference backend**: единичный контейнер vLLM (`llm-switchboard-backend`), управляется через Docker SDK.
- **Remote access**: через Tailscale (`tailscale serve`) или SSH port-forward.

## Quickstart (если код в GitHub)
```bash
# 1) клонируем проект на DGX Spark
sudo mkdir -p /opt
cd /opt
sudo git clone <YOUR_GITHUB_REPO_URL> llm-switchboard
cd /opt/llm-switchboard

# 2) ставим зависимости
./scripts/install_prereqs.sh
```

Создайте env-файл:
```bash
sudo tee /etc/llm-gateway.env >/dev/null <<'ENV'
GATEWAY_API_KEY=change-me
HF_TOKEN=
REDIS_URL=redis://127.0.0.1:6379/0
MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml
GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml
JUPYTER_TOKEN=change-jupyter-token
ENV
```

Запуск:
```bash
cd /opt/llm-switchboard
./scripts/pull_vllm_image.sh
./scripts/start_all.sh
```

Проверка:
```bash
curl -s http://127.0.0.1:8000/health
./scripts/smoke_test.sh
```


## Как запускать на DGX Spark
```bash
cd /opt/llm-switchboard

# создать/обновить env (обязательно: API ключ и пути к yaml)
sudo tee /etc/llm-gateway.env >/dev/null <<'ENV'
GATEWAY_API_KEY=change-me
HF_TOKEN=
REDIS_URL=redis://127.0.0.1:6379/0
MODELS_YAML_PATH=/opt/llm-switchboard/configs/models.yaml
GATEWAY_YAML_PATH=/opt/llm-switchboard/configs/gateway.yaml
JUPYTER_TOKEN=change-jupyter-token
ENV

# подтянуть vLLM image
./scripts/pull_vllm_image.sh

# поднять redis + systemd unit
./scripts/start_all.sh

# проверить
curl -s http://127.0.0.1:8000/health
```

## Как останавливать
```bash
cd /opt/llm-switchboard
./scripts/stop_all.sh

# либо вручную:
sudo systemctl stop llm-gateway.service llm-worker.service jupyter.service
docker compose -f docker/docker-compose.yml stop redis
docker rm -f llm-switchboard-backend || true
```

## Systemd команды
```bash
sudo systemctl enable --now llm-gateway.service
sudo systemctl enable --now llm-worker.service
sudo systemctl enable --now jupyter.service

journalctl -u llm-gateway -f
journalctl -u llm-worker -f
journalctl -u jupyter -f
```

## Модели: `configs/models.yaml`
Для каждой модели указывается:
- логическое имя `name`
- `source.type`: `huggingface_repo` или `local_path`
- `source.value`: HF repo id или локальный путь
- backend image/port/`vllm_args`
- директории кэша/моделей

Добавление новой модели:
1. Добавьте новый блок в `models:`.
2. Проверьте `vllm_args` (dtype/quantization/max-model-len).
3. Перезапустите gateway/worker.

## API
### OpenAI-like
- `GET /v1/models`
- `POST /v1/chat/completions`
  - default: async (`202 + job_id`)
  - sync при `"async": false` только если очередь пуста и модель уже активна.

### Jobs
- `POST /jobs`
- `GET /jobs/{id}`
- `GET /jobs/{id}/result`
- `POST /jobs/{id}/cancel`

### Admin
- `GET /health`
- `GET /status`
- `GET /queue`
- `POST /admin/switch`
- `POST /admin/drain?enable=true|false`

## Примеры curl
```bash
export API=http://127.0.0.1:8000
export KEY=change-me

curl -s -H "X-API-Key: $KEY" "$API/v1/models"

# async job
JOB_ID=$(curl -s -X POST "$API/v1/chat/completions" \
  -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"model":"gpt-oss120","async":true,"messages":[{"role":"user","content":"hello"}]}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["job_id"])')

echo "$JOB_ID"
curl -s -H "X-API-Key: $KEY" "$API/jobs/$JOB_ID"
curl -s -H "X-API-Key: $KEY" "$API/jobs/$JOB_ID/result"

# cancel
curl -s -X POST -H "X-API-Key: $KEY" "$API/jobs/$JOB_ID/cancel"
```


## Что делать дальше после git clone
1. Отредактировать `configs/models.yaml` под ваши реальные HF repo или локальные пути моделей.
2. При необходимости скачать веса заранее: `./scripts/download_models.sh`.
3. Проверить smoke: `./scripts/smoke_test.sh`.
4. Опубликовать API и Jupyter в tailnet через `tailscale serve` или SSH-forward.
5. Подключиться IDE (VS Code/PyCharm) и начать разработку.

## Tailscale доступ (безопасный)
Все сервисы bind на localhost, наружу публикуем только в tailnet.

### Вариант A: tailscale serve
```bash
tailscale serve --http=80 127.0.0.1:8000
# отдельно для jupyter
tailscale serve --http=8888 127.0.0.1:8888
```

### Вариант B: SSH port-forward
```bash
ssh -L 8000:127.0.0.1:8000 user@<tailscale-host>
ssh -L 8888:127.0.0.1:8888 user@<tailscale-host>
```

## VS Code / PyCharm
### VS Code
1. Remote-SSH на tailscale hostname.
2. Выберите interpreter `/opt/llm-switchboard/.venv/bin/python`.
3. Для ноутбуков подключитесь к Jupyter URL с token.

### PyCharm
1. Настройте SSH interpreter (Settings → Python Interpreter → Add SSH).
2. Проект на удалённой машине: `/opt/llm-switchboard`.
3. Для notebooks используйте Jupyter server URL через SSH/tailscale.

## Troubleshooting
- Логи inference backend:
  ```bash
  docker logs -f llm-switchboard-backend
  ```
- Если модель не стартует/OOM:
  - уменьшите `--max-model-len`
  - уменьшите `--gpu-memory-utilization`
  - проверьте quantization
- Ручная остановка backend:
  ```bash
  docker rm -f llm-switchboard-backend || true
  ```
- Проверка Redis:
  ```bash
  docker ps | grep llm-switchboard-redis
  redis-cli -h 127.0.0.1 -p 6379 ping
  ```

## Если позже понадобится k8s/k3s
Можно обернуть gateway/worker/redis в k3s и вынести switch-логику в singleton deployment + PVC lock, но это **вне текущей реализации**.
