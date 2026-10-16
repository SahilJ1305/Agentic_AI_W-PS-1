"""
Azure AI Foundry chat client (OpenAI-compatible chat completions).

Works with either endpoint style Foundry shows on a deployment page:
  https://<resource>.openai.azure.com/openai/v1             (no api-version)
  https://<resource>.services.ai.azure.com/models           (AZURE_AI_API_VERSION, e.g. 2024-05-01-preview)

The deployment name goes in the request body as `model`.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from pydantic import BaseModel

from app.config import settings


class AzureError(Exception):
    pass


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers={
                "api-key": settings.azure_ai_api_key,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(settings.llm_timeout_s, connect=10.0),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()


def _url(path: str) -> str:
    base = settings.azure_ai_endpoint.rstrip("/")
    url = f"{base}/{path.lstrip('/')}"
    if settings.azure_ai_api_version:
        url += f"?api-version={settings.azure_ai_api_version}"
    return url


async def chat(
    *,
    model: str,
    messages: list[dict[str, str]],
    response_schema: type[BaseModel] | None = None,
    timeout: float | None = None,
) -> tuple[str, dict]:
    """Send a chat request to an Azure deployment. Returns (reply_text, usage)."""
    if not settings.azure_ai_endpoint or not settings.azure_ai_api_key:
        raise AzureError("AZURE_AI_ENDPOINT and AZURE_AI_API_KEY must both be set")
    if not model:
        raise AzureError("No Azure deployment configured for this agent")

    payload: dict[str, Any] = {"model": model, "messages": messages}
    if response_schema is not None:
        payload["response_format"] = {"type": "json_object"}

    request_timeout = httpx.Timeout(timeout or settings.llm_timeout_s, connect=10.0)
    started = time.monotonic()
    response = await _post(payload, request_timeout)
    if response.status_code == 400 and "response_format" in payload and "response_format" in response.text:
        payload.pop("response_format")
        response = await _post(payload, request_timeout)
    if response.status_code >= 400:
        raise AzureError(f"Azure HTTP {response.status_code}: {response.text[:300]}")

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise AzureError("Azure returned no choices")
    content = choices[0].get("message", {}).get("content") or ""
    usage_raw = data.get("usage") or {}
    usage = {
        "prompt_tokens": usage_raw.get("prompt_tokens"),
        "completion_tokens": usage_raw.get("completion_tokens"),
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    return content, usage


async def _post(payload: dict, timeout: httpx.Timeout) -> httpx.Response:
    try:
        return await get_client().post(_url("chat/completions"), json=payload, timeout=timeout)
    except httpx.ConnectError as e:
        raise AzureError(f"Cannot reach Azure at {settings.azure_ai_endpoint}: {e}") from e
    except httpx.TimeoutException as e:
        raise AzureError(f"Azure timed out after {timeout.read}s") from e


async def list_models() -> list[str]:
    """The two configured deployments. Foundry has no shared list endpoint for both styles."""
    return [
        name for name in (
            settings.azure_coordinator_deployment,
            settings.azure_planner_deployment,
        ) if name
    ]
