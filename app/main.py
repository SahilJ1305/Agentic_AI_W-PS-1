"""
Cadence process.

Starts the API, Telegram polling, the outbox worker and the follow-up
scheduler in one asyncio loop. The board is the React app in frontend/;
logins come from backend/, which signs the JWTs this API checks.

    python -m app.main
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api import routes_admin, routes_projects, routes_reports, routes_tasks
from app.api.sse import broadcaster
from app.config import settings
from app.db import repo
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.telegram import log_filters
from app.telegram.gateway import (
    build_application,
    configure_bot,
    mark_bot_stopped,
    on_poll_error,
    set_sse_publish,
)

log = logging.getLogger(__name__)


async def _warm_azure() -> None:
    """Open the TLS connection and wake the deployment, so the first real reply is not the slow one."""
    from app.llm import azure

    if not (settings.azure_ai_endpoint and settings.azure_ai_api_key and settings.azure_coordinator_deployment):
        return
    try:
        await azure.chat(
            model=settings.azure_coordinator_deployment,
            messages=[{"role": "user", "content": "Reply with the word ready."}],
            timeout=30,
        )
        log.info("Azure coordinator deployment is warm")
    except Exception as exc:        # warming is best effort
        log.warning("Azure warm-up failed (the first reply may be slow): %s", exc)


async def _warm_ollama() -> None:
    """Touch the tunnel so the coordinator model is loaded before the first reply."""
    from app.llm.ollama import OllamaError, chat, list_models

    if not settings.coordinator_model:
        log.warning("COORDINATOR_MODEL is empty. Ollama replies cannot be interpreted.")
        return
    try:
        models = await list_models()
        log.info("Ollama is up. Models: %s", ", ".join(models) or "(none)")
        await chat(
            model=settings.coordinator_model,
            messages=[{"role": "user", "content": "Reply with the word ready."}],
            think=False,
            num_ctx=512,
            timeout=30,
        )
        log.info("Warmed coordinator model %s", settings.coordinator_model)
    except OllamaError as exc:
        log.warning(
            "Ollama is not reachable (%s). Start the tunnel with: ssh -fN ollama-server",
            exc,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log_filters.install()
    await repo.init_db()
    if not settings.secret_key:
        log.warning("SECRET_KEY is empty. Every board request will fail until it matches the backend's.")

    async def publish(event: str, payload: dict) -> None:
        await broadcaster.publish(event, payload)

    set_sse_publish(publish)

    bot = None
    outbox_task: asyncio.Task | None = None
    token = settings.telegram_bot_token.strip()
    if token:
        try:
            from app.telegram.outbox import run_outbox_worker

            bot = build_application()
            await bot.initialize()
            await bot.start()
            if bot.updater is None:
                raise RuntimeError("Telegram updater is unavailable")
            await configure_bot(bot)
            await bot.updater.start_polling(error_callback=on_poll_error)
            outbox_task = asyncio.create_task(run_outbox_worker(bot.bot))
            log.info("Telegram polling started as @%s", bot.bot.username)
        except Exception:
            log.exception("Telegram did not start; the API and dashboard stay up")
            bot = None
    else:
        log.warning("TELEGRAM_BOT_TOKEN is empty. Dashboard is live; the bot is not polling.")

    start_scheduler()
    if settings.llm_provider == "azure":
        log.info(
            "LLM provider: Azure (coordinator=%s, planner=%s)",
            settings.azure_coordinator_deployment or "unset",
            settings.azure_planner_deployment or "unset",
        )
        asyncio.create_task(_warm_azure())
    else:
        asyncio.create_task(_warm_ollama())
    try:
        yield
    finally:
        stop_scheduler()
        mark_bot_stopped()
        if outbox_task is not None:
            outbox_task.cancel()
            try:
                await outbox_task
            except asyncio.CancelledError:
                pass
        if bot is not None:
            if bot.updater is not None and bot.updater.running:
                await bot.updater.stop()
            if bot.running:
                await bot.stop()
            await bot.shutdown()


app = FastAPI(title="Cadence", lifespan=lifespan)
_origins = {settings.frontend_url.rstrip("/"), "http://localhost:5173", "http://127.0.0.1:5173"}
_origins |= {o.strip().rstrip("/") for o in settings.cors_origins.split(",") if o.strip()}
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(routes_projects.router, prefix="/api")
app.include_router(routes_tasks.router, prefix="/api")
app.include_router(routes_reports.router, prefix="/api")
app.include_router(routes_admin.public_router, prefix="/api")
app.include_router(routes_admin.router, prefix="/api")


@app.get("/")
async def dashboard():
    """The board lives in the React app now, behind login."""
    return RedirectResponse(f"{settings.frontend_url.rstrip('/')}/dashboard")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port)
