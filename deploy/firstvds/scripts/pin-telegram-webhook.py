from __future__ import annotations

import argparse
import ipaddress
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

REPO_DIR = Path(os.getenv("REPO_DIR", "/opt/bar-manager-ai"))
ENV_FILE = Path(
    os.getenv("ENV_FILE", str(REPO_DIR / "deploy" / "firstvds" / ".env"))
)
TELEGRAM_API_BASE = "https://api.telegram.org"
WEBHOOK_PATH = "/api/telegram/webhook"


class PinError(RuntimeError):
    pass


def read_env() -> dict[str, str]:
    if not ENV_FILE.exists():
        raise PinError(f"Environment file not found: {ENV_FILE}")

    values: dict[str, str] = {}
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def update_env_value(name: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    result: list[str] = []
    replaced = False

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            current_name, _ = line.split("=", 1)
            if current_name.strip() == name:
                result.append(f"{name}={value}")
                replaced = True
                continue
        result.append(line)

    if not replaced:
        if result and result[-1] != "":
            result.append("")
        result.append(f"{name}={value}")

    temporary = ENV_FILE.with_name(f"{ENV_FILE.name}.tmp")
    temporary.write_text("\n".join(result) + "\n", encoding="utf-8")
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    temporary.replace(ENV_FILE)
    ENV_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)


def telegram_call(
    token: str,
    method: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{TELEGRAM_API_BASE}/bot{token}/{method}"
    req = request.Request(
        url,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=40) as response:
            body = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        try:
            details = json.loads(exc.read().decode("utf-8", errors="replace"))
            description = details.get("description") or f"HTTP {exc.code}"
        except Exception:
            description = f"HTTP {exc.code}"
        raise PinError(f"Telegram API {method}: {description}") from None
    except (error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        raise PinError(f"Telegram API {method}: request failed") from None

    if not body.get("ok"):
        raise PinError(f"Telegram API {method}: request rejected")
    return body


def normalize_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        raise PinError("Invalid webhook IP address") from None
    if address.version != 4:
        raise PinError("Telegram webhook IP pinning currently expects an IPv4 address")
    return str(address)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pin the Telegram webhook to a fixed public IP without exposing secrets."
    )
    parser.add_argument(
        "--ip",
        help="Public IPv4 address of the current Bar Manager AI server.",
    )
    args = parser.parse_args()

    try:
        values = read_env()
        webhook_ip = normalize_ip(args.ip or values.get("TELEGRAM_WEBHOOK_IP", ""))
        token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
        secret = values.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
        api_domain = values.get("API_DOMAIN", "").strip()

        if not token:
            raise PinError("TELEGRAM_BOT_TOKEN is not configured")
        if not secret:
            raise PinError("TELEGRAM_WEBHOOK_SECRET is not configured")
        if not api_domain:
            raise PinError("API_DOMAIN is not configured")

        webhook_url = f"https://{api_domain}{WEBHOOK_PATH}"
        payload = {
            "url": webhook_url,
            "ip_address": webhook_ip,
            "secret_token": secret,
            "allowed_updates": ["message"],
            "drop_pending_updates": False,
        }
        telegram_call(token, "setWebhook", payload)
        info = telegram_call(token, "getWebhookInfo").get("result")
        if not isinstance(info, dict):
            raise PinError("Telegram returned invalid webhook information")
        if info.get("url") != webhook_url:
            raise PinError("Webhook URL verification failed")
        if info.get("ip_address") != webhook_ip:
            raise PinError("Webhook IP verification failed")

        update_env_value("TELEGRAM_WEBHOOK_IP", webhook_ip)

        print("Telegram webhook закреплён за новым сервером.")
        print(f"URL: {webhook_url}")
        print(f"IP: {webhook_ip}")
        print(f"Ожидающих обновлений: {info.get('pending_update_count', 0)}")
        return 0
    except PinError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
