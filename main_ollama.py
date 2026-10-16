"""
FastAPI gateway to a remote Ollama server, reached through an SSH tunnel.

Setup (on the machine that runs this app):
    1. Start the tunnel:   ssh -fN ollama-server      # localhost:11435 -> server 127.0.0.1:11434
    2. Install deps:       pip install fastapi uvicorn httpx
    3. Run the app:        uvicorn main:app --port 8000

Config (environment variables):
    OLLAMA_URL    default http://localhost:11435   (the tunnel's local end)
    OLLAMA_MODEL  default qwen2.5:3b-instruct-q4_K_M

Test:
    curl localhost:8000/health
    curl localhost:8000/chat -H 'Content-Type: application/json' \
         -d '{"messages":[{"role":"user","content":"Say hello in one sentence."}]}'
    curl -N localhost:8000/chat/stream -H 'Content-Type: application/json' \
         -d '{"messages":[{"role":"user","content":"Count to 5."}]}'
"""
import json
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11435")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b-instruct-q4_K_M")

TUNNEL_HINT = f"Cannot reach Ollama at {OLLAMA_URL}. Is the SSH tunnel running?"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One shared HTTP client. Short connect timeout so a dead tunnel fails fast;
    # long read timeout because the first request after idle loads the model.
    app.state.http = httpx.AsyncClient(
        base_url=OLLAMA_URL,
        timeout=httpx.Timeout(300.0, connect=5.0),
    )
    yield
    await app.state.http.aclose()


app = FastAPI(title="Ollama gateway", lifespan=lifespan)


class Message(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    model: str = DEFAULT_MODEL
    temperature: float = 0.7
    num_ctx: int | None = None  # e.g. 8192 for longer prompts (default is 4096 on this server)


def build_payload(req: ChatRequest, stream: bool) -> dict:
    options = {"temperature": req.temperature}
    if req.num_ctx:
        options["num_ctx"] = req.num_ctx
    return {
        "model": req.model,
        "messages": [m.model_dump() for m in req.messages],
        "stream": stream,
        "options": options,
    }


@app.get("/health")
async def health():
    """Checks the whole chain: app -> tunnel -> Ollama."""
    try:
        r = await app.state.http.get("/api/tags")
        r.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(503, TUNNEL_HINT)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Ollama error: {e}")
    return {"status": "ok", "models": [m["name"] for m in r.json()["models"]]}


@app.post("/chat")
async def chat(req: ChatRequest):
    """Non-streaming: returns the full reply as JSON."""
    try:
        r = await app.state.http.post("/api/chat", json=build_payload(req, stream=False))
        r.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(503, TUNNEL_HINT)
    except httpx.TimeoutException:
        raise HTTPException(504, "Ollama timed out")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)

    data = r.json()
    return {
        "reply": data["message"]["content"],
        "model": data["model"],
        "tokens_generated": data.get("eval_count"),
    }


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """Streaming: sends text chunks as Ollama generates them."""

    async def token_stream():
        try:
            async with app.state.http.stream(
                "POST", "/api/chat", json=build_payload(req, stream=True)
            ) as r:
                if r.status_code != 200:
                    body = (await r.aread()).decode()
                    yield f"\n[error {r.status_code}] {body}"
                    return
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        yield f"\n[error] {chunk['error']}"
                        return
                    yield chunk.get("message", {}).get("content", "")
                    if chunk.get("done"):
                        return
        except httpx.ConnectError:
            yield f"[error] {TUNNEL_HINT}"
        except httpx.TimeoutException:
            yield "\n[error] Ollama timed out"

    return StreamingResponse(token_stream(), media_type="text/plain")
