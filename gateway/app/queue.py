from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from rq import Queue
from rq.job import Job

from .config import get_gateway_config


def get_redis_conn() -> Redis:
    cfg = get_gateway_config()
    return Redis.from_url(os.getenv("REDIS_URL", cfg.redis_url), decode_responses=False)


def get_queue(name: str = "default") -> Queue:
    return Queue(name, connection=get_redis_conn(), default_timeout=get_gateway_config().timeouts.inference_timeout_sec)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def set_job_meta(job: Job, **kwargs: Any) -> None:
    for key, value in kwargs.items():
        job.meta[key] = value
    job.save_meta()


def parse_job_status(job: Job | None) -> str:
    if job is None:
        return "failed"
    if job.meta.get("cancelled"):
        return "cancelled"
    status = job.get_status(refresh=True)
    if status in {"queued", "started", "finished", "failed", "deferred", "scheduled", "stopped", "canceled"}:
        if status == "started":
            return "running"
        if status == "finished":
            return "succeeded"
        if status in {"canceled", "stopped"}:
            return "cancelled"
        return "failed" if status == "failed" else "queued"
    return "failed"
