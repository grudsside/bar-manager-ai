from pathlib import Path

from app.schemas import TelegramInboxTaskCreate
from app.telegram_inbox_analysis import (
    TelegramInboxAnalysis,
    fallback_inbox_analysis,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_fallback_analysis_requires_manual_review() -> None:
    analysis = fallback_inbox_analysis("Проверьте сообщение позже")

    assert analysis.classification == "unknown"
    assert analysis.confidence == 0
    assert analysis.needs_review is True
    assert analysis.suggested_task is None
    assert analysis.summary == "Проверьте сообщение позже"


def test_non_task_analysis_does_not_require_task_payload() -> None:
    analysis = TelegramInboxAnalysis(
        classification="writeoff",
        confidence=0.95,
        summary="Списаны две бутылки из-за повреждения этикетки",
        needs_review=False,
    )

    assert analysis.suggested_task is None
    assert analysis.classification == "writeoff"


def test_inbox_task_payload_validates_application_confirmation() -> None:
    payload = TelegramInboxTaskCreate(
        title="Проверить остатки сиропов",
        description="Сверить фактический остаток со складским отчётом",
        venue_code="oxford",
        priority="high",
        expected_result="Сформирован заказ недостающих позиций",
    )

    assert payload.venue_code == "oxford"
    assert payload.priority == "high"


def test_inbox_schema_and_deduplication_contract() -> None:
    migration = (
        REPO_ROOT
        / "backend"
        / "migrations"
        / "008_telegram_inbox_workflow.sql"
    ).read_text(encoding="utf-8")
    store = (
        REPO_ROOT / "backend" / "app" / "telegram_inbox_store.py"
    ).read_text(encoding="utf-8")

    assert "inbox_status" in migration
    assert "analysis jsonb" in migration
    assert "telegram_task_links_source_unique_idx" in migration
    assert "for update" in store
    assert "created_from_telegram_inbox" in store
    assert "TelegramInboxAlreadyProcessedError" in store
    assert "update telegram_messages" in store
    assert "inbox_status = 'confirmed'" in store


def test_application_api_exposes_inbox_and_chat_management() -> None:
    main_module = (REPO_ROOT / "backend" / "app" / "main.py").read_text(
        encoding="utf-8"
    )

    assert '"/api/inbox"' in main_module
    assert '"/api/inbox/{message_id}"' in main_module
    assert '"/api/inbox/{message_id}/task"' in main_module
    assert '"/api/telegram/chats"' in main_module
    assert '"/api/telegram/chats/{chat_id}"' in main_module
    assert "dependencies=[Depends(require_owner)]" in main_module


def test_frontend_uses_live_inbox_instead_of_demo_only_actions() -> None:
    api_client = (REPO_ROOT / "web" / "api-client.js").read_text(
        encoding="utf-8"
    )
    inbox_ui = (REPO_ROOT / "web" / "inbox-ui.js").read_text(
        encoding="utf-8"
    )
    service_worker = (REPO_ROOT / "web" / "service-worker.js").read_text(
        encoding="utf-8"
    )

    assert "listInbox(" in api_client
    assert "createTaskFromInbox(" in api_client
    assert "listTelegramChats(" in api_client
    assert "updateTelegramChat(" in api_client
    assert "renderInboxShell" in inbox_ui
    assert "data-create-inbox-task" in inbox_ui
    assert "data-chat-allowed" in inbox_ui
    assert "Privacy Mode" in inbox_ui
    assert "./inbox-ui.js" in service_worker
    assert "./inbox.css" in service_worker
