# Backend

FastAPI-сервис персонального ИИ-ассистента.

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Проверка состояния:

```text
GET /health
```

Защищённые API требуют заголовок `X-Owner-Key`. Telegram webhook требует секретный заголовок Telegram. Реальные значения хранятся только в переменных окружения.
