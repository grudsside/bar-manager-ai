from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .pending_action_store import get_pending_action_store
from .recurring_rules import (
    LOCAL_TIMEZONE,
    ExtractedRecurringRule,
    extract_recurring_rule,
    first_due_at,
    format_recurrence,
)
from .recurring_store import RecurringRuleOut, get_recurring_rule_store

RECURRING_COMMANDS = {"/repeat", "/recurring", "/disable_repeat"}
VENUE_LABELS = {
    "oxford": "Оксфорд",
    "sovremennik": "Современник",
    None: "Не указано",
}
PRIORITY_LABELS = {
    "low": "Низкий",
    "normal": "Обычный",
    "high": "Высокий",
    "critical": "Критический",
}


async def maybe_handle_recurring_command(
    text: str,
    *,
    chat_id: int,
    source_message_id: int | None,
    settings: Settings,
    send_text: Any,
    conversation_store: Any,
) -> bool:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", maxsplit=1)[0].lower() if parts else ""
    argument = parts[1].strip() if len(parts) > 1 else ""
    if command not in RECURRING_COMMANDS:
        return False

    pending_store = get_pending_action_store(settings.database_url)
    recurring_store = get_recurring_rule_store(settings.database_url)

    async def reply(message: str) -> None:
        await send_text(
            settings,
            chat_id,
            message,
            store=conversation_store,
            reply_to_message_id=source_message_id,
        )

    if recurring_store is None or pending_store is None:
        await reply("Повторяющиеся задачи недоступны: база данных не подключена.")
        return True

    if command == "/repeat":
        if not argument:
            await reply(
                "После команды укажите повторяющееся поручение. Например:\n"
                "/repeat Оксфорд — каждый понедельник в 10:00 проверить остатки сиропов"
            )
            return True

        draft = await extract_recurring_rule(argument, settings)
        if draft.clarification_question:
            await reply(
                f"{draft.clarification_question}\n\n"
                "После уточнения отправьте полное правило командой /repeat ещё раз."
            )
            return True
        if draft.due_time is None:
            await reply("Не удалось определить время выполнения. Укажите его явно.")
            return True

        next_due = first_due_at(
            draft,
            now=datetime.now(timezone.utc),
        )
        payload = draft.model_dump(mode="json")
        payload.update(
            {
                "original_text": argument,
                "next_due_at": next_due.isoformat(),
            }
        )
        await pending_store.save_recurring_rule(
            chat_id,
            payload,
            source_message_id=source_message_id,
        )
        await reply(_format_rule_preview(draft, next_due))
        return True

    rules = await recurring_store.list_rules(enabled_only=True)
    if command == "/recurring":
        await reply(_format_rule_list(rules))
        return True

    rule = _select_rule(rules, argument)
    if rule is None:
        await reply(
            "Не удалось определить правило. Сначала отправьте /recurring, затем "
            "укажите номер, например /disable_repeat 1."
        )
        return True

    await pending_store.save_disable_recurring_rule(
        chat_id,
        rule_id=rule.id,
        title=rule.title,
        source_message_id=source_message_id,
    )
    await reply(
        "Подтверждение отключения повторяющейся задачи\n"
        f"Правило: {rule.title}\n"
        f"Расписание: {format_recurrence(rule.frequency, rule.weekdays, rule.due_time)}\n\n"
        "Для отключения отправьте /confirm.\n"
        "Для отмены отправьте /cancel."
    )
    return True


def _format_rule_preview(
    draft: ExtractedRecurringRule,
    next_due: datetime,
) -> str:
    if draft.due_time is None:
        raise ValueError("Recurring rule due_time is required")
    return (
        "Проект повторяющейся задачи\n"
        f"Задача: {draft.title}\n"
        f"Заведение: {VENUE_LABELS.get(draft.venue_code, 'Не указано')}\n"
        f"Приоритет: {PRIORITY_LABELS.get(draft.priority, draft.priority)}\n"
        f"Расписание: {format_recurrence(draft.frequency, draft.weekdays, draft.due_time)}\n"
        f"Ближайший срок: {_format_datetime(next_due)}\n\n"
        "Для создания правила отправьте /confirm.\n"
        "Для отмены отправьте /cancel."
    )


def _format_rule_list(rules: list[RecurringRuleOut]) -> str:
    if not rules:
        return "Активных повторяющихся задач пока нет."

    lines = ["Повторяющиеся задачи:"]
    for index, rule in enumerate(rules[:10], start=1):
        venue = VENUE_LABELS.get(rule.venue_code, "Не указано")
        schedule = format_recurrence(rule.frequency, rule.weekdays, rule.due_time)
        next_due = (
            _format_datetime(rule.next_due_at)
            if rule.next_due_at is not None
            else "не определён"
        )
        lines.append(
            f"{index}. {rule.title}\n"
            f"   {venue} · {schedule}\n"
            f"   ближайший срок: {next_due}"
        )
    if len(rules) > 10:
        lines.append("Показаны первые 10 правил.")
    lines.extend(
        [
            "",
            "/disable_repeat N — отключить правило после подтверждения",
        ]
    )
    return "\n".join(lines)


def _select_rule(
    rules: list[RecurringRuleOut],
    argument: str,
) -> RecurringRuleOut | None:
    try:
        number = int(argument.strip())
    except (TypeError, ValueError):
        return None
    if number < 1 or number > len(rules):
        return None
    return rules[number - 1]


def _format_datetime(value: datetime) -> str:
    localized = value
    if localized.tzinfo is None:
        localized = localized.replace(tzinfo=timezone.utc)
    return localized.astimezone(LOCAL_TIMEZONE).strftime("%d.%m.%Y %H:%M")
