"""
Cadence process.

Starts the API, the live dashboard, Telegram polling, the outbox worker
and the follow-up scheduler in one asyncio loop.

    python -m app.main
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api import routes_admin, routes_projects, routes_tasks
from app.api.sse import broadcaster
from app.config import settings
from app.db import repo
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.telegram.gateway import build_application, set_sse_publish

log = logging.getLogger(__name__)
_DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await repo.init_db()

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
            await bot.updater.start_polling()
            outbox_task = asyncio.create_task(run_outbox_worker(bot.bot))
            log.info("Telegram polling started")
        except Exception:
            log.exception("Telegram did not start; the API and dashboard stay up")
            bot = None
    else:
        log.warning("TELEGRAM_BOT_TOKEN is empty. Dashboard is live; the bot is not polling.")

    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(routes_projects.router, prefix="/api")
app.include_router(routes_tasks.router, prefix="/api")
app.include_router(routes_admin.router, prefix="/api")


@app.get("/")
async def dashboard():
    return FileResponse(_DASHBOARD, media_type="text/html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
