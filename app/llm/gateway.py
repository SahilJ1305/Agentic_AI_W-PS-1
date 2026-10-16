"""
app/llm/gateway.py — fallback chain, repair retry, and logging.

Fallback chain (Coordinator):
  1. Ollama (LLM_TIMEOUT_S)
  2. OpenCode Console (LLM_TIMEOUT_S)
  3. Raise LLMFailure → Policy Engine falls back to button clarification (R15)

Fallback chain (Planner):
  1. Ollama (PLANNER_TIMEOUT_S — model may need to load)
  2. OpenCode Console (PLANNER_TIMEOUT_S)
  3. Raise LLMFailure

Every attempt is logged to llm_calls via repo.log_llm_call().
On a parse error, one repair attempt is made by appending an error message
to the conversation before retrying the same provider.
"""
from __future__ import annotations

import json
import logging
from typing import Literal

import aiosqlite
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.db import repo
from app.llm import ollama as _ollama
from app.llm import openai_compat as _opencode

log = logging.getLogger(__name__)


class LLMFailure(Exception):
    """Raised when all providers fail and no structured output is available."""


AgentType = Literal["planner", "coordinator", "composer"]


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
    model_primary = settings.planner_model if is_planner else settings.coordinator_model
    model_fallback = settings.opencode_model
    num_ctx = settings.planner_num_ctx if is_planner else settings.coordinator_num_ctx
    think = settings.planner_think if is_planner else settings.coordinator_think
    timeout = settings.planner_timeout_s if is_planner else settings.llm_timeout_s

    # Add schema instruction to system message for OpenCode (which doesn't use format=)
    schema_instruction = (
        f"\n\nRespond ONLY with a JSON object matching this schema:\n"
        f"{json.dumps(response_schema.model_json_schema(), indent=2)}"
    )

    errors: list[str] = []

    # ── Attempt 1: Ollama ──────────────────────────────────────────────────────
    try:
        text, usage = await _ollama.chat(
            model=model_primary,
            messages=messages,
            response_schema=response_schema,
            think=think,
            num_ctx=num_ctx,
            timeout=timeout,
        )
        result, parse_err = _try_parse(response_schema, text)
        if result is not None:
            await _log(db, agent=agent, provider="ollama", model=model_primary,
                       messages=messages, text=text, parsed_ok=True,
                       usage=usage, now=now)
            return result

        # Repair retry: send the parse error back to Ollama
        repair_messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"The JSON you returned could not be parsed: {parse_err}. Please return valid JSON only."},
        ]
        text2, usage2 = await _ollama.chat(
            model=model_primary,
            messages=repair_messages,
            response_schema=response_schema,
            think=False,
            num_ctx=num_ctx,
            timeout=timeout,
        )
        result2, parse_err2 = _try_parse(response_schema, text2)
        await _log(db, agent=agent, provider="ollama", model=model_primary,
                   messages=repair_messages, text=text2,
                   parsed_ok=result2 is not None,
                   error=parse_err2, usage=usage2, now=now)
        if result2 is not None:
            return result2
        errors.append(f"Ollama parse error after repair: {parse_err2}")

    except _ollama.OllamaError as e:
        errors.append(f"Ollama: {e}")
        log.warning("Ollama failed for agent=%s: %s", agent, e)

    # ── Attempt 2: OpenCode Console ────────────────────────────────────────────
    if not settings.opencode_api_key:
        raise LLMFailure(f"All LLM providers failed. Errors: {errors}")

    try:
        # Inject schema into system message for OpenCode (JSON mode only)
        opencode_messages = _inject_schema(messages, schema_instruction)
        text3, usage3 = await _opencode.chat(
            model=model_fallback,
            messages=opencode_messages,
            response_schema=response_schema,
            timeout=timeout,
        )
        result3, parse_err3 = _try_parse(response_schema, text3)
        if result3 is not None:
            await _log(db, agent=agent, provider="opencode", model=model_fallback,
                       messages=opencode_messages, text=text3, parsed_ok=True,
                       usage=usage3, now=now)
            return result3

        # Repair retry on OpenCode
        repair_oc = opencode_messages + [
            {"role": "assistant", "content": text3},
            {"role": "user", "content": f"Invalid JSON: {parse_err3}. Return valid JSON only."},
        ]
        text4, usage4 = await _opencode.chat(
            model=model_fallback,
            messages=repair_oc,
            response_schema=response_schema,
            timeout=timeout,
        )
        result4, parse_err4 = _try_parse(response_schema, text4)
        await _log(db, agent=agent, provider="opencode", model=model_fallback,
                   messages=repair_oc, text=text4,
                   parsed_ok=result4 is not None,
                   error=parse_err4, usage=usage4, now=now)
        if result4 is not None:
            return result4
        errors.append(f"OpenCode parse error after repair: {parse_err4}")

    except _opencode.OpenCodeError as e:
        errors.append(f"OpenCode: {e}")
        log.warning("OpenCode failed for agent=%s: %s", agent, e)

    raise LLMFailure(f"All LLM providers failed. Errors: {errors}")


# ── helpers ────────────────────────────────────────────────────────────────────

def _try_parse(
    schema: type[BaseModel], text: str
) -> tuple[BaseModel | None, str | None]:
    """
    Try to parse `text` as JSON and validate against the Pydantic schema.
    Returns (model_instance, None) on success or (None, error_string) on failure.
    """
    try:
        data = json.loads(text)
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
