from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TimeoutsConfig(BaseModel):
    switch_timeout_sec: int = 180
    inference_timeout_sec: int = 3600
    backend_ready_timeout_sec: int = 180


class PoliciesConfig(BaseModel):
    default_async: bool = True
    sync_allowed_only_if_queue_empty_and_model_active: bool = True
    when_switching: str = "wait"
    wait_timeout_sec: int = 60


class GatewayConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    redis_url: str = "redis://127.0.0.1:6379/0"
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    policies: PoliciesConfig = Field(default_factory=PoliciesConfig)


class ModelSource(BaseModel):
    type: str
    value: str


class BackendConfig(BaseModel):
    image: str = "nvcr.io/nvidia/vllm:25.11-py3"
    port: int = 8001
    vllm_args: list[str] = Field(default_factory=list)


class ModelResources(BaseModel):
    hf_cache_dir: str = "/var/lib/huggingface"
    models_dir: str = "/mnt/models"


class ModelConfig(BaseModel):
    name: str
    source: ModelSource
    backend: BackendConfig
    resources: ModelResources = Field(default_factory=ModelResources)
    notes: str | None = None


class ModelsConfig(BaseModel):
    models: list[ModelConfig]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


@lru_cache(maxsize=1)
def get_gateway_config() -> GatewayConfig:
    path = Path(os.getenv("GATEWAY_YAML_PATH", "configs/gateway.yaml"))
    data = _load_yaml(path)
    cfg = GatewayConfig.model_validate(data)
    redis_from_env = os.getenv("REDIS_URL")
    if redis_from_env:
        cfg.redis_url = redis_from_env
    return cfg


@lru_cache(maxsize=1)
def get_models_config() -> ModelsConfig:
    path = Path(os.getenv("MODELS_YAML_PATH", "configs/models.yaml"))
    data = _load_yaml(path)
    return ModelsConfig.model_validate(data)


def get_model_map() -> dict[str, ModelConfig]:
    return {m.name: m for m in get_models_config().models}


def get_api_key() -> str | None:
    return os.getenv("GATEWAY_API_KEY")
