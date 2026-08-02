from pathlib import Path

from app.config import Settings
from app.schemas import HealthResponse

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_health_response_carries_release_version() -> None:
    settings = Settings(app_version="abc123", _env_file=None)
    response = HealthResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment="test",
        openai_configured=False,
        telegram_configured=False,
        database_configured=False,
    )

    assert response.version == "abc123"


def test_deployment_verifies_container_commit() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    compose = (
        REPO_ROOT / "deploy" / "firstvds" / "docker-compose.yml"
    ).read_text(encoding="utf-8")
    deploy = (
        REPO_ROOT / "deploy" / "firstvds" / "scripts" / "deploy.sh"
    ).read_text(encoding="utf-8")

    assert "ARG APP_VERSION=dev" in dockerfile
    assert "APP_VERSION=${APP_VERSION}" in dockerfile
    assert "APP_VERSION: ${APP_VERSION:-dev}" in compose
    assert 'container_version="$(docker exec bar-manager-ai-api printenv APP_VERSION)"' in deploy
    assert "Health version mismatch" in deploy
