from __future__ import annotations

from typing import Any

import httpx


class BackendProxyError(RuntimeError):
    pass


def invoke_chat_completion(port: int, payload: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            json=payload,
            timeout=timeout_sec,
        )
    except httpx.HTTPError as exc:
        raise BackendProxyError(f"Failed to call backend: {exc}") from exc

    if response.status_code >= 400:
        raise BackendProxyError(f"Backend error: {response.status_code} {response.text}")
    return response.json()
