from __future__ import annotations

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

Ты не должен самостоятельно отправлять сообщения, удалять данные, менять сроки или
закрывать важные задачи. Для таких действий всегда указывай, что требуется подтверждение владельца.
Отвечай на русском языке, структурировано и без лишней теории.
""".strip()


def build_agent(settings: Settings) -> Agent:
    kwargs: dict[str, object] = {
        "name": "Бар-менеджер AI",
        "instructions": SYSTEM_INSTRUCTIONS,
    }
    if settings.openai_model:
        kwargs["model"] = settings.openai_model
    return Agent(**kwargs)


async def run_agent(request: AgentChatRequest, settings: Settings) -> AgentChatResponse:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    context_text = ""
    if request.context:
        context_text = f"\n\nКонтекст приложения:\n{request.context}"
    if request.task_id:
        context_text += f"\nАктивная задача: {request.task_id}"

    result = await Runner.run(
        build_agent(settings),
        request.message + context_text,
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
