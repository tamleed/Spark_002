from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from typing import Any

import docker
import httpx
from docker.errors import DockerException, ImageNotFound, NotFound
from redis import Redis

from .config import ModelConfig

CONTAINER_NAME = "llm-switchboard-backend"
LOCK_PATH = "/var/lock/llm-switch.lock"
ACTIVE_MODEL_KEY = "switchboard:active_model"
SWITCHING_KEY = "switchboard:switching"
CURRENT_JOB_KEY = "switchboard:current_job"
DRAIN_MODE_KEY = "switchboard:drain_mode"


class BackendSwitchError(RuntimeError):
    pass


class Switcher:
    def __init__(self, redis_conn: Redis, switch_timeout: int, ready_timeout: int):
        self.redis = redis_conn
        self.switch_timeout = switch_timeout
        self.ready_timeout = ready_timeout
        self.docker_client = docker.from_env()

    @contextmanager
    def _file_lock(self):
        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        with open(LOCK_PATH, "w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def get_active_model(self) -> str | None:
        val = self.redis.get(ACTIVE_MODEL_KEY)
        return val.decode() if val else None

    def get_switching(self) -> bool:
        return self.redis.get(SWITCHING_KEY) == b"1"

    def set_current_job(self, job_id: str | None) -> None:
        if job_id:
            self.redis.set(CURRENT_JOB_KEY, job_id)
        else:
            self.redis.delete(CURRENT_JOB_KEY)

    def get_current_job(self) -> str | None:
        val = self.redis.get(CURRENT_JOB_KEY)
        return val.decode() if val else None

    def set_drain_mode(self, enabled: bool) -> None:
        self.redis.set(DRAIN_MODE_KEY, "1" if enabled else "0")

    def get_drain_mode(self) -> bool:
        return self.redis.get(DRAIN_MODE_KEY) == b"1"

    def ensure_image(self, image: str) -> None:
        try:
            self.docker_client.images.get(image)
        except ImageNotFound as exc:
            raise BackendSwitchError(
                f"vLLM image '{image}' is not available. Run scripts/pull_vllm_image.sh first."
            ) from exc

    def stop_current_backend(self) -> None:
        try:
            container = self.docker_client.containers.get(CONTAINER_NAME)
        except NotFound:
            self.redis.delete(ACTIVE_MODEL_KEY)
            return

        try:
            container.stop(timeout=min(20, self.switch_timeout))
        except DockerException:
            container.kill()

        deadline = time.time() + self.switch_timeout
        while time.time() < deadline:
            container.reload()
            if container.status in {"exited", "dead", "created"}:
                break
            time.sleep(1)
        try:
            container.remove(force=True)
        except DockerException:
            pass
        self.redis.delete(ACTIVE_MODEL_KEY)

    def start_backend(self, model: ModelConfig) -> None:
        self.ensure_image(model.backend.image)
        self.stop_current_backend()

        command = [
            "python",
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--host",
            "0.0.0.0",
            "--port",
            str(model.backend.port),
            "--model",
            model.source.value,
            *model.backend.vllm_args,
        ]

        env = {}
        hf_token = os.getenv("HF_TOKEN")
        if hf_token:
            env["HF_TOKEN"] = hf_token

        volumes: dict[str, dict[str, str]] = {
            model.resources.hf_cache_dir: {"bind": "/root/.cache/huggingface", "mode": "rw"},
            model.resources.models_dir: {"bind": "/models", "mode": "rw"},
        }

        if model.source.type == "local_path":
            volumes[model.source.value] = {"bind": model.source.value, "mode": "ro"}

        try:
            self.docker_client.containers.run(
                image=model.backend.image,
                name=CONTAINER_NAME,
                command=command,
                detach=True,
                remove=False,
                network_mode="host",
                environment=env,
                volumes=volumes,
                runtime="nvidia",
                restart_policy={"Name": "no"},
            )
        except DockerException as exc:
            raise BackendSwitchError(f"Failed to start backend container: {exc}") from exc

        self._wait_ready(model.backend.port)
        self.redis.set(ACTIVE_MODEL_KEY, model.name)

    def _wait_ready(self, port: int) -> None:
        deadline = time.time() + self.ready_timeout
        last_error: str | None = None
        while time.time() < deadline:
            try:
                response = httpx.get(f"http://127.0.0.1:{port}/v1/models", timeout=5.0)
                if response.status_code == 200:
                    return
                last_error = f"status={response.status_code} body={response.text[:500]}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(2)
        logs = self._read_backend_logs()
        raise BackendSwitchError(
            f"Backend readiness timeout after {self.ready_timeout}s. Last error: {last_error}. Logs: {logs}"
        )

    def _read_backend_logs(self) -> str:
        try:
            container = self.docker_client.containers.get(CONTAINER_NAME)
            raw = container.logs(tail=200)
            return raw.decode(errors="ignore")[-4000:]
        except Exception:  # noqa: BLE001
            return "<logs unavailable>"

    def switch_to_model(self, model: ModelConfig) -> None:
        with self._file_lock():
            self.redis.set(SWITCHING_KEY, "1")
            try:
                self.start_backend(model)
            finally:
                self.redis.set(SWITCHING_KEY, "0")

    def hard_cancel_running(self) -> None:
        with self._file_lock():
            self.redis.set(SWITCHING_KEY, "1")
            try:
                self.stop_current_backend()
                self.set_current_job(None)
            finally:
                self.redis.set(SWITCHING_KEY, "0")
