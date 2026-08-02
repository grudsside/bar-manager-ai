from __future__ import annotations

import getpass
import json
import os
import secrets
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

REPO_DIR = Path(os.getenv("REPO_DIR", "/opt/bar-manager-ai"))
ENV_FILE = Path(
    os.getenv("ENV_FILE", str(REPO_DIR / "deploy" / "firstvds" / ".env"))
)
COMPOSE_FILE = REPO_DIR / "deploy" / "firstvds" / "docker-compose.yml"
TELEGRAM_API_BASE = "https://api.telegram.org"
WEBHOOK_PATH = "/api/telegram/webhook"


class SetupError(RuntimeError):
    pass


def telegram_call(
    token: str,
    method: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 40,
) -> dict[str, Any]:
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    body = json.dumps(payload or {}).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        try:
            details = json.loads(exc.read().decode("utf-8", errors="replace"))
            description = details.get("description") or f"HTTP {exc.code}"
        except Exception:
            description = f"HTTP {exc.code}"
        raise SetupError(f"Telegram API {method}: {description}") from None
    except (error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", None)
        safe_reason = type(reason).__name__ if reason is not None else type(exc).__name__
        raise SetupError(f"Telegram API {method}: network error ({safe_reason})") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SetupError(f"Telegram API {method}: invalid response") from None

    if not data.get("ok"):
        raise SetupError(f"Telegram API {method}: request rejected")
    return data


def extract_private_chat_id(updates: list[dict[str, Any]]) -> int | None:
    for update in reversed(updates):
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat")
        if not isinstance(chat, dict) or chat.get("type") != "private":
            continue
        chat_id = chat.get("id")
        if isinstance(chat_id, int):
            return chat_id
    return None


def update_env_text(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    remaining = dict(updates)
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            result.append(line)
            continue
        name, _ = line.split("=", 1)
        key = name.strip()
        if key in remaining:
            result.append(f"{key}={remaining.pop(key)}")
        else:
            result.append(line)

    if remaining:
        if result and result[-1] != "":
            result.append("")
        for key, value in remaining.items():
            result.append(f"{key}={value}")

    return "\n".join(result) + "\n"


def write_env(updates: dict[str, str]) -> None:
    if not ENV_FILE.exists():
        raise SetupError(f"Environment file not found: {ENV_FILE}")
    current = ENV_FILE.read_text(encoding="utf-8")
    updated = update_env_text(current, updates)
    temporary = ENV_FILE.with_suffix(".env.tmp")
    temporary.write_text(updated, encoding="utf-8")
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    temporary.replace(ENV_FILE)
    ENV_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)


def read_env_value(name: str) -> str:
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=REPO_DIR, check=True)


def wait_for_container_health(timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
                "bar-manager-ai-api",
            ],
            cwd=REPO_DIR,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip() == "healthy":
            return
        time.sleep(3)
    raise SetupError("API container did not become healthy")


def wait_for_owner_update(token: str, timeout_seconds: int = 150) -> int:
    deadline = time.monotonic() + timeout_seconds
    offset: int | None = None
    print("Ищу ваше сообщение /start в Telegram…", flush=True)

    while time.monotonic() < deadline:
        payload: dict[str, Any] = {
            "timeout": 20,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        response = telegram_call(token, "getUpdates", payload, timeout=30)
        updates = response.get("result")
        if not isinstance(updates, list):
            updates = []

        chat_id = extract_private_chat_id(updates)
        if chat_id is not None:
            return chat_id

        update_ids = [
            item.get("update_id")
            for item in updates
            if isinstance(item, dict) and isinstance(item.get("update_id"), int)
        ]
        if update_ids:
            offset = max(update_ids) + 1
        print("Сообщение пока не найдено. Отправьте боту /start — ожидание продолжается…", flush=True)

    raise SetupError("Не найдено личное сообщение боту. Отправьте /start и запустите настройку ещё раз.")


def main() -> int:
    if os.geteuid() != 0:
        print("Запустите скрипт от root.", file=sys.stderr)
        return 1
    if not COMPOSE_FILE.exists():
        print(f"Compose file not found: {COMPOSE_FILE}", file=sys.stderr)
        return 1

    try:
        token = getpass.getpass("Вставьте Telegram bot token — ввод скрыт: ").strip()
        if not token:
            raise SetupError("Telegram bot token is empty")

        bot = telegram_call(token, "getMe").get("result")
        if not isinstance(bot, dict):
            raise SetupError("Telegram getMe returned no bot data")
        bot_username = str(bot.get("username") or "unknown")
        print(f"Токен проверен. Бот: @{bot_username}")

        telegram_call(token, "deleteWebhook", {"drop_pending_updates": False})
        owner_chat_id = wait_for_owner_update(token)
        webhook_secret = secrets.token_urlsafe(32)
        api_domain = read_env_value("API_DOMAIN")
        if not api_domain:
            raise SetupError("API_DOMAIN is not configured in .env")

        write_env(
            {
                "TELEGRAM_BOT_TOKEN": token,
                "TELEGRAM_WEBHOOK_SECRET": webhook_secret,
                "OWNER_TELEGRAM_ID": str(owner_chat_id),
            }
        )
        token = ""
        print(f"Telegram ID найден и сохранён: {owner_chat_id}")

        print("Загружаю актуальный код и пересобираю API…")
        run(["git", "fetch", "origin", "main"])
        run(["git", "checkout", "main"])
        run(["git", "reset", "--hard", "origin/main"])
        run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ENV_FILE),
                "-f",
                str(COMPOSE_FILE),
                "build",
                "api",
            ]
        )
        run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ENV_FILE),
                "-f",
                str(COMPOSE_FILE),
                "up",
                "-d",
                "--force-recreate",
                "--remove-orphans",
                "api",
            ]
        )
        wait_for_container_health()

        stored_token = read_env_value("TELEGRAM_BOT_TOKEN")
        webhook_url = f"https://{api_domain}{WEBHOOK_PATH}"
        webhook_result = telegram_call(
            stored_token,
            "setWebhook",
            {
                "url": webhook_url,
                "secret_token": webhook_secret,
                "allowed_updates": ["message"],
                "drop_pending_updates": True,
            },
        )
        if not webhook_result.get("result"):
            raise SetupError("Telegram did not accept the webhook")

        webhook_info = telegram_call(stored_token, "getWebhookInfo").get("result")
        if not isinstance(webhook_info, dict) or webhook_info.get("url") != webhook_url:
            raise SetupError("Webhook verification failed")

        print()
        print("Telegram подключён успешно.")
        print(f"Бот: @{bot_username}")
        print(f"Owner Telegram ID: {owner_chat_id}")
        print(f"Webhook: {webhook_url}")
        print("Теперь снова отправьте боту /start.")
        return 0
    except SetupError as exc:
        print(f"Ошибка настройки: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Команда завершилась с ошибкой: {exc.cmd}", file=sys.stderr)
        return exc.returncode or 1
    finally:
        try:
            token = ""
        except UnboundLocalError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
