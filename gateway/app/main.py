from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response
from redis.exceptions import RedisError
from rq.command import send_stop_job_command
from rq.job import Job

from .auth import require_api_key
from .config import get_gateway_config, get_model_map
from .models import (
    AdminSwitchRequest,
    ChatCompletionRequest,
    HealthResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
    QueueStatusResponse,
    StatusResponse,
)
from .queue import get_queue, get_redis_conn, parse_job_status, set_job_meta, utc_now_iso
from .switcher import Switcher

START_TIME = time.time()
app = FastAPI(title="LLM Switchboard")


def _job_to_status(job: Job) -> JobStatusResponse:
    meta = job.meta or {}
    return JobStatusResponse(
        id=job.id,
        status=parse_job_status(job),
        requested_model=meta.get("requested_model", "unknown"),
        created_at=datetime.fromisoformat(meta["created_at"]) if meta.get("created_at") else None,
        started_at=datetime.fromisoformat(meta["started_at"]) if meta.get("started_at") else None,
        finished_at=datetime.fromisoformat(meta["finished_at"]) if meta.get("finished_at") else None,
        progress=meta.get("progress"),
        error=meta.get("error"),
    )


def _enqueue_job(payload: dict[str, Any], high_priority: bool = False) -> JobCreateResponse:
    queue_name = "admin" if high_priority else "default"
    queue = get_queue(queue_name)
    timeout = get_gateway_config().timeouts.inference_timeout_sec
    job = queue.enqueue(
        "worker.tasks.execute_job",
        payload,
        job_timeout=timeout,
        result_ttl=86400,
        failure_ttl=86400,
    )
    set_job_meta(
        job,
        requested_model=payload.get("model"),
        created_at=utc_now_iso(),
        started_at=None,
        finished_at=None,
        progress=0.0,
        error=None,
        cancelled=False,
    )
    return JobCreateResponse(job_id=job.id)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        get_redis_conn().ping()
        redis_state = "ok"
    except RedisError:
        redis_state = "unavailable"
    return HealthResponse(status="ok", redis=redis_state)


@app.get("/status", response_model=StatusResponse, dependencies=[Depends(require_api_key)])
def status() -> StatusResponse:
    cfg = get_gateway_config()
    queue = get_queue("default")
    switcher = Switcher(get_redis_conn(), cfg.timeouts.switch_timeout_sec, cfg.timeouts.backend_ready_timeout_sec)
    return StatusResponse(
        active_model=switcher.get_active_model(),
        uptime_sec=time.time() - START_TIME,
        switching=switcher.get_switching(),
        current_job_id=switcher.get_current_job(),
        queue_length=len(queue),
        drain_mode=switcher.get_drain_mode(),
    )


@app.get("/v1/models", dependencies=[Depends(require_api_key)])
def list_models() -> dict[str, Any]:
    model_map = get_model_map()
    cfg = get_gateway_config()
    switcher = Switcher(get_redis_conn(), cfg.timeouts.switch_timeout_sec, cfg.timeouts.backend_ready_timeout_sec)
    active = switcher.get_active_model()
    return {
        "object": "list",
        "data": [
            {
                "id": name,
                "object": "model",
                "owned_by": "local",
                "active": name == active,
            }
            for name in model_map
        ],
    }


@app.post("/v1/chat/completions", dependencies=[Depends(require_api_key)])
def chat_completions(request: ChatCompletionRequest, response: Response) -> dict[str, Any]:
    cfg = get_gateway_config()
    model_map = get_model_map()
    if request.model not in model_map:
        raise HTTPException(status_code=404, detail="Model not found")

    async_mode = cfg.policies.default_async if request.async_mode is None else request.async_mode
    payload = request.model_dump(by_alias=True)
    payload.pop("async", None)

    if async_mode:
        response.status_code = 202
        return _enqueue_job(payload).model_dump()

    queue = get_queue("default")
    switcher = Switcher(get_redis_conn(), cfg.timeouts.switch_timeout_sec, cfg.timeouts.backend_ready_timeout_sec)
    if len(queue) > 0 or switcher.get_active_model() != request.model:
        raise HTTPException(
            status_code=409,
            detail="Queue not empty or model switch required; use async",
        )

    from .proxy import invoke_chat_completion

    result = invoke_chat_completion(
        port=model_map[request.model].backend.port,
        payload=payload,
        timeout_sec=cfg.timeouts.inference_timeout_sec,
    )
    return result


@app.post("/jobs", response_model=JobCreateResponse, status_code=202, dependencies=[Depends(require_api_key)])
def create_job(request: JobCreateRequest) -> JobCreateResponse:
    model_map = get_model_map()
    if request.model not in model_map:
        raise HTTPException(status_code=404, detail="Model not found")
    return _enqueue_job(request.model_dump())


@app.get("/jobs/{job_id}", response_model=JobStatusResponse, dependencies=[Depends(require_api_key)])
def get_job(job_id: str) -> JobStatusResponse:
    job = Job.fetch(job_id, connection=get_redis_conn())
    return _job_to_status(job)


@app.get("/jobs/{job_id}/result", dependencies=[Depends(require_api_key)])
def get_job_result(job_id: str) -> dict[str, Any]:
    job = Job.fetch(job_id, connection=get_redis_conn())
    status = parse_job_status(job)
    if status == "succeeded":
        return job.result
    if status == "cancelled":
        raise HTTPException(status_code=409, detail="Job cancelled")
    if status == "failed":
        raise HTTPException(status_code=500, detail=job.meta.get("error", "Job failed"))
    raise HTTPException(status_code=202, detail="Job not finished")


@app.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_api_key)])
def cancel_job(job_id: str) -> dict[str, Any]:
    redis_conn = get_redis_conn()
    cfg = get_gateway_config()
    switcher = Switcher(redis_conn, cfg.timeouts.switch_timeout_sec, cfg.timeouts.backend_ready_timeout_sec)

    job = Job.fetch(job_id, connection=redis_conn)
    status = parse_job_status(job)
    if status == "queued":
        job.cancel()
        set_job_meta(job, cancelled=True, finished_at=utc_now_iso())
        return {"job_id": job_id, "status": "cancelled"}

    if status == "running":
        try:
            send_stop_job_command(redis_conn, job_id)
        except Exception:
            pass
        switcher.hard_cancel_running()
        set_job_meta(job, cancelled=True, finished_at=utc_now_iso(), error="Cancelled by user")
        return {"job_id": job_id, "status": "cancelled"}

    return {"job_id": job_id, "status": status}


@app.get("/queue", response_model=QueueStatusResponse, dependencies=[Depends(require_api_key)])
def queue_status() -> QueueStatusResponse:
    cfg = get_gateway_config()
    switcher = Switcher(get_redis_conn(), cfg.timeouts.switch_timeout_sec, cfg.timeouts.backend_ready_timeout_sec)
    queue = get_queue("default")
    return QueueStatusResponse(
        queue_length=len(queue),
        current_job_id=switcher.get_current_job(),
        current_model=switcher.get_active_model(),
        switching=switcher.get_switching(),
        drain_mode=switcher.get_drain_mode(),
    )


@app.post("/admin/switch", status_code=202, dependencies=[Depends(require_api_key)])
def admin_switch(request: AdminSwitchRequest) -> JobCreateResponse:
    model_map = get_model_map()
    if request.model not in model_map:
        raise HTTPException(status_code=404, detail="Model not found")
    payload = {"model": request.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1, "admin_switch": True}
    return _enqueue_job(payload, high_priority=True)


@app.post("/admin/drain", dependencies=[Depends(require_api_key)])
def admin_drain(enable: bool = True) -> dict[str, Any]:
    cfg = get_gateway_config()
    switcher = Switcher(get_redis_conn(), cfg.timeouts.switch_timeout_sec, cfg.timeouts.backend_ready_timeout_sec)
    switcher.set_drain_mode(enable)
    return {"drain_mode": switcher.get_drain_mode()}
