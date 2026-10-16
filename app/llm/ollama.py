"""
app/llm/ollama.py — async Ollama client via SSH tunnel.

Talks to localhost:11435 (the tunnel's local end).
Uses Ollama's native /api/chat with schema-constrained output (format field).
Extends / replaces the standalone main_ollama.py in the repo root.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import settings


class OllamaError(Exception):
    pass


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(settings.planner_timeout_s, connect=5.0),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()


async def chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    response_schema: type[BaseModel] | None = None,
    think: bool = False,
    num_ctx: int = 8192,
    timeout: float | None = None,
) -> tuple[str, dict]:
    """
    Send a chat request to Ollama.

    Returns:
        (reply_text, usage_dict)
    Raises:
        OllamaError on connection or HTTP errors.
    """
    client = get_client()

    options: dict[str, Any] = {"num_ctx": num_ctx}
    if not think:
        options["think"] = False

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }

    if response_schema is not None:
        payload["format"] = response_schema.model_json_schema()

    request_timeout = httpx.Timeout(timeout or settings.llm_timeout_s, connect=5.0)

    t0 = time.monotonic()
    try:
        r = await client.post("/api/chat", json=payload, timeout=request_timeout)
        r.raise_for_status()
    except httpx.ConnectError as e:
        raise OllamaError(f"Cannot reach Ollama at {settings.ollama_base_url}: {e}") from e
    except httpx.TimeoutException as e:
        raise OllamaError(f"Ollama timed out after {timeout or settings.llm_timeout_s}s") from e
    except httpx.HTTPStatusError as e:
        raise OllamaError(f"Ollama HTTP {e.response.status_code}: {e.response.text}") from e

    latency_ms = int((time.monotonic() - t0) * 1000)
    data = r.json()

    # Strip any leaked <think>...</think> blocks (safety net)
    content: str = data.get("message", {}).get("content", "")
    content = _strip_think(content)

    usage = {
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": data.get("eval_count"),
        "latency_ms": latency_ms,
    }
    return content, usage


def _strip_think(text: str) -> str:
    """Remove any <think>...</think> blocks that leak despite think=false."""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def list_models() -> list[str]:
    """Return model names available on the Ollama server."""
    client = get_client()
    try:
        r = await client.get("/api/tags", timeout=httpx.Timeout(10.0, connect=5.0))
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except (httpx.ConnectError, httpx.HTTPError) as e:
        raise OllamaError(str(e)) from e
