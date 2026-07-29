import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "Бар-менеджер AI API"
    assert isinstance(payload["openai_configured"], bool)
    assert isinstance(payload["telegram_configured"], bool)


def test_agent_endpoint_is_closed_without_owner_configuration() -> None:
    response = client.post(
        "/api/agent/chat",
        json={"message": "Что мне делать сегодня?"},
    )
    assert response.status_code == 503


def test_tasks_endpoint_is_closed_without_owner_configuration() -> None:
    response = client.get("/api/tasks")
    assert response.status_code == 503


def test_telegram_webhook_is_closed_without_secret() -> None:
    response = client.post(
        "/api/telegram/webhook",
        json={"update_id": 1},
    )
    assert response.status_code == 503


def test_task_create_list_and_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER_API_KEY", "test-owner-key")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    headers = {"X-Owner-Key": "test-owner-key"}

    try:
        created_response = client.post(
            "/api/tasks",
            headers=headers,
            json={
                "title": "Проверить ревизию кофе",
                "venue_code": "sovremennik",
                "priority": "high",
                "status": "new",
                "source_type": "manual",
            },
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["title"] == "Проверить ревизию кофе"
        assert created["venue_name"] == "Современник"
        assert created["completed_at"] is None

        list_response = client.get("/api/tasks?status=new", headers=headers)
        assert list_response.status_code == 200
        assert any(item["id"] == created["id"] for item in list_response.json())

        updated_response = client.patch(
            f"/api/tasks/{created['id']}",
            headers=headers,
            json={"status": "done"},
        )
        assert updated_response.status_code == 200
        updated = updated_response.json()
        assert updated["status"] == "done"
        assert updated["completed_at"] is not None
    finally:
        get_settings.cache_clear()
