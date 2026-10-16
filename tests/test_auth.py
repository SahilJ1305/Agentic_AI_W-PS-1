"""Cadence trusts only tokens signed with the backend's SECRET_KEY and scopes projects to their owner."""
from __future__ import annotations

import asyncio

import jwt
from fastapi.testclient import TestClient

from app.config import settings
from app.db.seed_demo import seed
from tests.conftest import auth_header


def _client(tmp_path, name: str):
    settings.database_path = str(tmp_path / name)
    settings.telegram_bot_token = ""
    settings.coordinator_model = ""
    asyncio.run(seed(force=True))
    from app.main import app
    return TestClient(app)


def test_board_requires_login(tmp_path):
    with _client(tmp_path, "login.db") as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/projects").status_code == 401
        assert client.get("/api/projects/1/tasks").status_code == 401

        forged = jwt.encode({"sub": "x@example.com", "user_id": 9}, "a-different-secret-that-is-also-long-enough", algorithm="HS256")
        bad = client.get("/api/projects", headers={"Authorization": f"Bearer {forged}"})
        assert bad.status_code == 401

        expired = client.get("/api/projects", headers=auth_header(minutes=-5))
        assert expired.status_code == 401
        assert "expired" in expired.json()["detail"]

        home = client.get("/", follow_redirects=False)
        assert home.status_code == 307
        assert home.headers["location"].endswith("/dashboard")


def test_projects_belong_to_the_user_who_created_them(tmp_path):
    alice = auth_header(1, "alice@example.com")
    bob = auth_header(2, "bob@example.com")
    with _client(tmp_path, "owners.db") as client:
        mine = client.post("/api/projects", json={"name": "Alice's thesis"}, headers=alice).json()
        assert mine["owner_user_id"] == 1

        alice_sees = {p["name"] for p in client.get("/api/projects", headers=alice).json()}
        bob_sees = {p["name"] for p in client.get("/api/projects", headers=bob).json()}
        assert alice_sees == {"FestPass", "Alice's thesis"}
        assert bob_sees == {"FestPass"}

        pid = mine["id"]
        assert client.get(f"/api/projects/{pid}", headers=bob).status_code == 404
        assert client.get(f"/api/projects/{pid}/tasks", headers=bob).status_code == 404
        assert client.post(
            "/api/admin/checkin", json={"project_id": pid}, headers=bob,
        ).status_code == 404

        festpass_tasks = client.get("/api/projects/1/tasks", headers=bob).json()
        task_id = festpass_tasks[0]["id"]
        assert client.get(f"/api/tasks/{task_id}", headers=bob).status_code == 200


def test_live_stream_accepts_token_in_url(tmp_path):
    with _client(tmp_path, "stream.db") as client:
        token = auth_header()["Authorization"].split(" ", 1)[1]
        assert client.get("/api/projects/1/stream").status_code == 401
        with client.stream("GET", f"/api/projects/1/stream?token={token}") as response:
            assert response.status_code == 200
            first = next(response.iter_lines())
            assert first == "event: connected"
