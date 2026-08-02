from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT / "deploy" / "firstvds" / "scripts" / "verify-production.py"
)
SPEC = importlib.util.spec_from_file_location("verify_production", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
verify_production = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_production)


def test_normalize_base_url_adds_https_and_removes_trailing_slash() -> None:
    assert (
        verify_production.normalize_base_url("api.gridsside.ru/")
        == "https://api.gridsside.ru"
    )


def test_validate_health_requires_current_release_and_all_integrations() -> None:
    data = {
        "service": "Bar Manager AI",
        "version": "abcdef123456",
        "environment": "production",
        "database_configured": True,
        "openai_configured": True,
        "telegram_configured": True,
    }

    assert verify_production.validate_health(data, "abcdef123456") is data

    disabled = dict(data, openai_configured=False)
    with pytest.raises(
        verify_production.VerificationError,
        match="openai_configured",
    ):
        verify_production.validate_health(disabled, "abcdef123456")

    with pytest.raises(
        verify_production.VerificationError,
        match="version mismatch",
    ):
        verify_production.validate_health(data, "000000000000")


def test_validate_owner_endpoints_requires_json_lists() -> None:
    assert verify_production.validate_list_endpoint([], "/api/inbox") == 0
    assert verify_production.validate_list_endpoint([{"id": "1"}], "/api/inbox") == 1

    with pytest.raises(
        verify_production.VerificationError,
        match="JSON list",
    ):
        verify_production.validate_list_endpoint({}, "/api/inbox")


def test_validate_webhook_info_checks_url_and_optional_ip() -> None:
    response = {
        "ok": True,
        "result": {
            "url": "https://api.gridsside.ru/api/telegram/webhook",
            "ip_address": "203.0.113.10",
            "pending_update_count": 0,
        },
    }

    info = verify_production.validate_webhook_info(
        response,
        expected_url="https://api.gridsside.ru/api/telegram/webhook",
        expected_ip="203.0.113.10",
    )
    assert info["pending_update_count"] == 0

    with pytest.raises(
        verify_production.VerificationError,
        match="webhook URL",
    ):
        verify_production.validate_webhook_info(
            response,
            expected_url="https://wrong.example/api/telegram/webhook",
            expected_ip=None,
        )
