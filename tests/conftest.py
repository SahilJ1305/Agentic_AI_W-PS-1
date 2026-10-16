from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings

TEST_SECRET = "test-secret-not-for-production-use-0123456789"


@pytest.fixture(autouse=True)
def shared_secret(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", TEST_SECRET)


def auth_header(user_id: int = 1, email: str = "lead@example.com", *, minutes: int = 60) -> dict:
    """The same claims backend/auth/token.py puts in a login token."""
    token = jwt.encode(
        {
            "sub": email,
            "user_id": user_id,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
        },
        TEST_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}
