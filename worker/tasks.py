from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rq import get_current_job

from gateway.app.config import get_gateway_config, get_model_map
from gateway.app.proxy import BackendProxyError, invoke_chat_completion
from gateway.app.queue import get_redis_conn, set_job_meta
from gateway.app.switcher import BackendSwitchError, Switcher


def _now() -> str:
    return datetime.now(UTC).isoformat()


def execute_job(payload: dict[str, Any]) -> dict[str, Any]:
    job = get_current_job()
    if job is None:
        raise RuntimeError("No current RQ job context")

    cfg = get_gateway_config()
    redis_conn = get_redis_conn()
    switcher = Switcher(redis_conn, cfg.timeouts.switch_timeout_sec, cfg.timeouts.backend_ready_timeout_sec)
    model_map = get_model_map()

    requested_model = payload.get("model")
    if requested_model not in model_map:
        set_job_meta(job, error="Model not found", finished_at=_now())
        raise RuntimeError("Model not found")

    if switcher.get_drain_mode() and not payload.get("admin_switch"):
        set_job_meta(job, error="Gateway is in drain mode", finished_at=_now())
        raise RuntimeError("Gateway is in drain mode")

    set_job_meta(job, started_at=_now(), progress=0.05)
    switcher.set_current_job(job.id)

    try:
        if switcher.get_active_model() != requested_model:
            switcher.switch_to_model(model_map[requested_model])

        set_job_meta(job, progress=0.3)
        result = invoke_chat_completion(
            port=model_map[requested_model].backend.port,
            payload=payload,
            timeout_sec=cfg.timeouts.inference_timeout_sec,
        )

        set_job_meta(job, progress=1.0, finished_at=_now())
        return result

    except (BackendSwitchError, BackendProxyError, Exception) as exc:
        set_job_meta(job, error=str(exc), finished_at=_now())
        raise
    finally:
        switcher.set_current_job(None)
