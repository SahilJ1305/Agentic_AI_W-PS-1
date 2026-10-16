"""
app/llm/gateway.py — fallback chain, repair retry, and logging.

Chain for both agents:
  1. LLM_PROVIDER: Ollama (COORDINATOR_MODEL / PLANNER_MODEL)
     or Azure AI Foundry (AZURE_COORDINATOR_DEPLOYMENT / AZURE_PLANNER_DEPLOYMENT)
  2. OpenCode Console, when OPENCODE_API_KEY is set
  3. Raise LLMFailure → the router asks with buttons (R15)

Every attempt is logged to llm_calls via repo.log_llm_call().
A response that does not match the schema gets one repair retry on the same provider.
"""
from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable, Literal

import aiosqlite
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.db import repo
from app.llm import azure as _azure
from app.llm import ollama as _ollama
from app.llm import openai_compat as _opencode

log = logging.getLogger(__name__)


class LLMFailure(Exception):
    """Raised when all providers fail and no structured output is available."""


AgentType = Literal["planner", "coordinator", "composer"]
ChatFn = Callable[[list[dict[str, str]], bool], Awaitable[tuple[str, dict]]]


async def call_llm(
    agent: AgentType,
    messages: list[dict[str, str]],
    response_schema: type[BaseModel],
    *,
    db: aiosqlite.Connection,
    now: str,
) -> BaseModel:
    """
    Call the LLM with the fallback chain.

    Returns a validated Pydantic model instance.
    Raises LLMFailure if all providers fail.
    """
    is_planner = agent == "planner"
    timeout = settings.planner_timeout_s if is_planner else settings.llm_timeout_s
    schema_instruction = (
        f"\n\nRespond ONLY with a JSON object matching this schema:\n"
        f"{json.dumps(response_schema.model_json_schema(), indent=2)}"
    )
    with_schema = _inject_schema(messages, schema_instruction)
    errors: list[str] = []

    if settings.llm_provider == "azure":
        deployment = (
            settings.azure_planner_deployment if is_planner else settings.azure_coordinator_deployment
        )

        async def azure_chat(msgs, _repairing):
            return await _azure.chat(
                model=deployment, messages=msgs, response_schema=response_schema, timeout=timeout,
            )

        primary = ("azure", deployment, with_schema, azure_chat, _azure.AzureError)
    else:
        model = settings.planner_model if is_planner else settings.coordinator_model
        think = settings.planner_think if is_planner else settings.coordinator_think
        num_ctx = settings.planner_num_ctx if is_planner else settings.coordinator_num_ctx

        async def ollama_chat(msgs, repairing):
            return await _ollama.chat(
                model=model,
                messages=msgs,
                response_schema=response_schema,
                think=False if repairing else think,
                num_ctx=num_ctx,
                timeout=timeout,
            )

        primary = ("ollama", model, messages, ollama_chat, _ollama.OllamaError)

    result = await _attempt(*primary, response_schema, agent, db, now, errors)
    if result is not None:
        return result

    if settings.opencode_api_key:
        async def opencode_chat(msgs, _repairing):
            return await _opencode.chat(
                model=settings.opencode_model,
                messages=msgs,
                response_schema=response_schema,
                timeout=timeout,
            )

        result = await _attempt(
            "opencode", settings.opencode_model, with_schema, opencode_chat,
            _opencode.OpenCodeError, response_schema, agent, db, now, errors,
        )
        if result is not None:
            return result

    raise LLMFailure(f"All LLM providers failed. Errors: {errors}")


async def _attempt(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    chat: ChatFn,
    error_type: type[Exception],
    schema: type[BaseModel],
    agent: str,
    db: aiosqlite.Connection,
    now: str,
    errors: list[str],
) -> BaseModel | None:
    """One call plus one repair retry on a single provider. Returns None on failure."""
    if not model:
        errors.append(f"{provider}: no model or deployment configured for {agent}")
        return None
    try:
        text, usage = await chat(messages, False)
        result, parse_err = _try_parse(schema, text)
        await _log(db, agent=agent, provider=provider, model=model, messages=messages,
                   text=text, parsed_ok=result is not None, error=parse_err, usage=usage, now=now)
        if result is not None:
            return result

        repair = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"The JSON you returned could not be parsed: {parse_err}. Return valid JSON only."},
        ]
        text2, usage2 = await chat(repair, True)
        result2, parse_err2 = _try_parse(schema, text2)
        await _log(db, agent=agent, provider=provider, model=model, messages=repair,
                   text=text2, parsed_ok=result2 is not None, error=parse_err2, usage=usage2, now=now)
        if result2 is not None:
            return result2
        errors.append(f"{provider} parse error after repair: {parse_err2}")
    except error_type as e:
        errors.append(f"{provider}: {e}")
        log.warning("%s failed for agent=%s: %s", provider, agent, e)
    return None


# ── helpers ────────────────────────────────────────────────────────────────────

def _try_parse(
    schema: type[BaseModel], text: str
) -> tuple[BaseModel | None, str | None]:
    """
    Parse `text` as JSON and validate it. Tolerates ```json fences some hosted models add.
    Returns (model_instance, None) on success or (None, error_string) on failure.
    """
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
        return schema.model_validate(data), None
    except json.JSONDecodeError as e:
        return None, f"JSONDecodeError: {e}"
    except ValidationError as e:
        return None, f"ValidationError: {e}"


def _inject_schema(
    messages: list[dict[str, str]], schema_instruction: str
) -> list[dict[str, str]]:
    """
    Append the schema instruction to the first system message found,
    or prepend a new system message if none exists.
    """
    result = list(messages)
    for i, m in enumerate(result):
        if m.get("role") == "system":
            result[i] = {**m, "content": m["content"] + schema_instruction}
            return result
    result.insert(0, {"role": "system", "content": schema_instruction.strip()})
    return result


async def _log(
    db: aiosqlite.Connection,
    *,
    agent: str,
    provider: str,
    model: str,
    messages: list[dict],
    text: str | None,
    parsed_ok: bool,
    error: str | None = None,
    usage: dict | None = None,
    now: str,
) -> None:
    usage = usage or {}
    try:
        await repo.log_llm_call(
            db,
            agent=agent,
            provider=provider,
            model=model,
            request_json=json.dumps(messages),
            response_text=text,
            parsed_ok=parsed_ok,
            error=error,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=usage.get("latency_ms"),
            now=now,
        )
    except Exception:
        log.exception("Failed to log LLM call")
