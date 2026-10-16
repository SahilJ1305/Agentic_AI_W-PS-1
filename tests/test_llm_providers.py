"""LLM_PROVIDER switches the primary model between Ollama and Azure AI Foundry."""
from __future__ import annotations

import asyncio
import json

import httpx

from app.agents.schemas import Interpretation
from app.config import settings
from app.db import repo
from app.llm import azure as azure_client
from app.llm.gateway import LLMFailure, call_llm

_REPLY = {
    "intent": "status_update",
    "updates": [{
        "task_key": "T3",
        "status": "blocked",
        "blocker": {"description": "test credentials", "kind": "external"},
    }],
}


def _messages():
    return [
        {"role": "system", "content": "You are the Coordinator."},
        {"role": "user", "content": "connected, waiting for test credentials"},
    ]


def test_azure_provider_sends_deployment_and_key(tmp_path, monkeypatch):
    settings.database_path = str(tmp_path / "azure.db")
    monkeypatch.setattr(settings, "llm_provider", "azure")
    monkeypatch.setattr(settings, "azure_ai_endpoint", "https://demo.services.ai.azure.com/models")
    monkeypatch.setattr(settings, "azure_ai_api_key", "secret-key")
    monkeypatch.setattr(settings, "azure_ai_api_version", "2024-05-01-preview")
    monkeypatch.setattr(settings, "azure_coordinator_deployment", "FW-GLM-5.3-Flash")
    monkeypatch.setattr(settings, "opencode_api_key", "")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "```json\n" + json.dumps(_REPLY) + "\n```"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 30},
        })

    monkeypatch.setattr(
        azure_client,
        "_client",
        httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"api-key": "secret-key"},
        ),
    )

    async def run():
        await repo.init_db()
        async with repo.db_context() as db:
            return await call_llm("coordinator", _messages(), Interpretation, db=db, now="2026-10-16T17:00:00+00:00")

    result = asyncio.run(run())
    assert result.updates[0].status == "blocked"
    assert seen["url"] == "https://demo.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview"
    assert seen["key"] == "secret-key"
    assert seen["body"]["model"] == "FW-GLM-5.3-Flash"
    assert "Respond ONLY with a JSON object" in seen["body"]["messages"][0]["content"]


def test_azure_endpoint_copied_with_operation_path(monkeypatch):
    monkeypatch.setattr(settings, "azure_ai_api_version", "")
    for pasted in (
        "https://demo.services.ai.azure.com/openai/v1/responses",
        "https://demo.services.ai.azure.com/openai/v1/chat/completions/",
        "https://demo.services.ai.azure.com/openai/v1",
    ):
        monkeypatch.setattr(settings, "azure_ai_endpoint", pasted)
        assert azure_client._url("chat/completions") == (
            "https://demo.services.ai.azure.com/openai/v1/chat/completions"
        )


def test_azure_without_deployment_fails_cleanly(tmp_path, monkeypatch):
    settings.database_path = str(tmp_path / "azure-missing.db")
    monkeypatch.setattr(settings, "llm_provider", "azure")
    monkeypatch.setattr(settings, "azure_coordinator_deployment", "")
    monkeypatch.setattr(settings, "opencode_api_key", "")

    async def run():
        await repo.init_db()
        async with repo.db_context() as db:
            await call_llm("coordinator", _messages(), Interpretation, db=db, now="2026-10-16T17:00:00+00:00")

    try:
        asyncio.run(run())
    except LLMFailure as exc:
        assert "no model or deployment configured" in str(exc)
    else:
        raise AssertionError("expected LLMFailure")


def test_ollama_stays_the_default(tmp_path, monkeypatch):
    settings.database_path = str(tmp_path / "ollama.db")
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "coordinator_model", "qwen2.5:3b-instruct-q4_K_M")
    calls: list[str] = []

    async def fake_chat(**kwargs):
        calls.append(kwargs["model"])
        return json.dumps(_REPLY), {"latency_ms": 5}

    from app.llm import ollama as ollama_client
    monkeypatch.setattr(ollama_client, "chat", fake_chat)

    async def run():
        await repo.init_db()
        async with repo.db_context() as db:
            return await call_llm("coordinator", _messages(), Interpretation, db=db, now="2026-10-16T17:00:00+00:00")

    result = asyncio.run(run())
    assert calls == ["qwen2.5:3b-instruct-q4_K_M"]
    assert result.updates[0].blocker.description == "test credentials"
