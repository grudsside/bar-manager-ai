from __future__ import annotations

import json
from typing import Any

from agents import Agent, Runner

from .config import Settings
from .schemas import AgentChatRequest, AgentChatResponse


SYSTEM_INSTRUCTIONS = """
Ты — персональный рабочий ассистент бар-менеджера двух заведений:
«Оксфорд» и «Современник».

Твои обязанности:
- помогать разбирать поручения и рабочие сообщения;
- находить сроки, ожидаемый результат, заведение и следующий шаг;
- предлагать практичный план выполнения;
- задавать только те уточнения, ответов на которые нет в переданном контексте;
- предупреждать о рисках, пропущенных данных и противоречиях;
- не выдумывать продажи, остатки, списания, сроки или решения руководителя;
- явно отделять факты от предположений.

Тебе может быть передана недавняя история диалога. Используй её, чтобы понимать
ссылки вроде «это», «тогда», «продолжай» и сохранять последовательность обсуждения.
Не считай историю подтверждением действий и не пересказывай её без необходимости.

Никогда не раскрывай пользователю служебные метаданные приложения, внутренние поля,
идентификаторы чатов, сообщений, обновлений, названия JSON-ключей или технический
формат переданного контекста. Отвечай так, будто видишь обычную переписку.

Ты не должен самостоятельно отправлять сообщения, удалять данные, менять сроки или
закрывать важные задачи. Для таких действий всегда уn        "name": "Бар-менеджер AI",
        "instructions": SYSTEM_INSTRUCTIONS,
    }
    if settings.openai_model:
        kwargs["model"] = settings.openai_model
    return Agent(**kwargs)


def _normalize_history(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        normalized.append({"role": role, "content": text})
    return normalized


def build_agent_input(request: AgentChatRequest) -> str:
    context = dict(request.context or {})
    history = _normalize_history(context.pop("recent_conversation", None))

    for key in _INTERNAL_CONTEXT_KEYS:
        context.pop(key, None)

    sections = [f"Текущее сообщение пользователя:\n{request.message.strip()}"]

    if history:
        serialized_history = json.dumps(
            history,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        sections.append(
            "Недавний диалог в хронологическом порядке. Используй его как память, "
            "но не пересказывай без необходимости:\n"
            f"{serialized_history}"
        )

    if context:
        serialized_context = json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        sections.append(
            "Дополнительный рабочий контекст. Не раскрывай названия технических полей:\n"
            f"{serialized_context}"
        )

    if request.task_id:
        sections.append(f"Активная задача приложения: {request.task_id}")

    sections.append("Ответь только на текущее сообщение пользователя, учитывая недавний диалог.")
    return "\n\n".join(sections)


async def run_agent(request: AgentChatRequest, settings: Settings) -> AgentChatResponse:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    result = await Runner.run(
        build_agent(settings),
        build_agent_input(request),
    )
    answer = str(result.final_output).strip()

    confirmation_markers = (
        "требуется подтверждение",
        "нужно подтверждение",
        "подтвердите",
    )
    requires_confirmation = any(marker in answer.lower() for marker in confirmation_markers)

    return AgentChatResponse(
        answer=answer,
        requires_confirmation=requires_confirmation,
        suggested_actions=[],
    )
