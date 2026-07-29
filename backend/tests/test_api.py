from fastapi.testclient import TestClient

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


def test_telegram_webhook_is_closed_without_secret() -> None:
    response = client.post(
        "/api/telegram/webhook",
        json={"update_id": 1},
    )
    assert response.status_code == 503
