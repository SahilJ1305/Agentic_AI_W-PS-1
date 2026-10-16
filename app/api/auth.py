"""
Login check for the Cadence API.

Accounts live in the backend service (Postgres). It signs an HS256 JWT with
SECRET_KEY carrying `sub` (email) and `user_id`; Cadence verifies the same
token and never stores passwords.

Projects with no owner (the seeded FestPass demo) are visible to every
logged-in user. Everything else is visible only to the user who created it.
"""
from __future__ import annotations

from dataclasses import dataclass

import aiosqlite
import jwt
from fastapi import HTTPException, Request

from app.config import settings
from app.db import repo


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def _token_from(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    # EventSource cannot send headers, so the live stream passes the token in the URL.
    return request.query_params.get("token") or None


async def current_user(request: Request) -> CurrentUser:
    if not settings.secret_key:
        raise HTTPException(503, "SECRET_KEY is not set, so Cadence cannot verify logins.")
    token = _token_from(request)
    if not token:
        raise _unauthorized("Log in first.")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Your session expired. Log in again.")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid login token. Log in again.")
    user_id = payload.get("user_id")
    email = payload.get("sub")
    if user_id is None or not email:
        raise _unauthorized("Invalid login token. Log in again.")
    return CurrentUser(id=int(user_id), email=str(email))


def can_see(project: dict | None, user: CurrentUser) -> bool:
    return bool(project) and project.get("owner_user_id") in (None, user.id)


async def visible_project(db: aiosqlite.Connection, project_id: int, user: CurrentUser) -> dict:
    project = await repo.get_project(db, project_id)
    if not can_see(project, user):
        raise HTTPException(404, "Project not found")
    return project


async def visible_task(db: aiosqlite.Connection, task_id: int, user: CurrentUser) -> dict:
    task = await repo.get_task(db, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if not can_see(await repo.get_project(db, task["project_id"]), user):
        raise HTTPException(404, "Task not found")
    return task
