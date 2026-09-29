import pytest


@pytest.mark.asyncio
async def test_health(client, monkeypatch, tmp_path):
    from types import SimpleNamespace

    import src.main

    # Ping DB thật (SQLite tạm) thay vì DATABASE_URL trong .env của máy dev.
    monkeypatch.setattr(src.main, "get_settings", lambda: SimpleNamespace(database_url=f"sqlite:///{tmp_path}/h.db"))
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_chat_empty_message(client):
    response = await client.post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_agent_status(client):
    response = await client.get("/api/v1/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_reports_database_down(client, monkeypatch):
    from src.services.orchestration.jobs import database

    def broken(self):
        raise OSError("db down")

    monkeypatch.setattr(database.RuntimeDatabase, "ping", broken)
    response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "error"
