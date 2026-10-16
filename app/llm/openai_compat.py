"""
app/llm/openai_compat.py — OpenCode Console free-model client.

OpenCode Console exposes an OpenAI-compatible endpoint at:
  https://opencode.ai/inference/openai/v1/chat/completions

We use the openai Python library (or httpx directly).
Uses JSON mode via response_format={"type": "json_object"}.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import settings


class OpenCodeError(Exception):
    pass


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.opencode_base_url,
            headers={
                "Authorization": f"Bearer {settings.opencode_api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(settings.llm_timeout_s, connect=10.0),
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
    timeout: float | None = None,
) -> tuple[str, dict]:
    """
    Send a chat request to the OpenCode Console.

    Returns:
        (reply_text, usage_dict)
    Raises:
        OpenCodeError on connection or auth errors.
    """
    if not settings.opencode_api_key:
        raise OpenCodeError("OPENCODE_API_KEY is not set — fallback unavailable")

    client = get_client()

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    if response_schema is not None:
        # Ask for JSON mode; the schema is embedded in the system prompt by the gateway
        payload["response_format"] = {"type": "json_object"}

    request_timeout = httpx.Timeout(timeout or settings.llm_timeout_s, connect=10.0)

    t0 = time.monotonic()
    try:
        r = await client.post(
            "/chat/completions", json=payload, timeout=request_timeout
        )
        r.raise_for_status()
    except httpx.ConnectError as e:
        raise OpenCodeError(f"Cannot reach OpenCode Console: {e}") from e
    except httpx.TimeoutException:
        raise OpenCodeError(f"OpenCode timed out after {timeout or settings.llm_timeout_s}s")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200]
        raise OpenCodeError(f"OpenCode HTTP {e.response.status_code}: {body}") from e

    latency_ms = int((time.monotonic() - t0) * 1000)
    data = r.json()

    choices = data.get("choices", [])
    if not choices:
        raise OpenCodeError("OpenCode returned no choices")

    content: str = choices[0].get("message", {}).get("content", "")
    usage_raw = data.get("usage", {})
    usage = {
        "prompt_tokens": usage_raw.get("prompt_tokens"),
        "completion_tokens": usage_raw.get("completion_tokens"),
        "latency_ms": latency_ms,
    }
    return content, usage


async def list_models() -> list[str]:
    """Fetch available free models from the OpenCode Console."""
    client = get_client()
    try:
        r = await client.get("/models", timeout=httpx.Timeout(10.0, connect=10.0))
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]
    except (httpx.ConnectError, httpx.HTTPError) as e:
        raise OpenCodeError(str(e)) from e
