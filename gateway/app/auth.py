from __future__ import annotations

from fastapi import Header, HTTPException

from .config import get_api_key


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_api_key()
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")
