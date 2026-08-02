from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib import error, request

REPO_DIR = Path(os.getenv("REPO_DIR", "/opt/bar-manager-ai"))
DEFAULT_ENV_FILE = REPO_DIR / "deploy" / "firstvds" / ".env"
DEFAULT_FRONTEND_URL = "https://grudsside.github.io/bar-manager-ai"
REQUIRED_HEALTH_FLAGS = (
    "database_configured",
    "openai_configured",
    "telegram_configured",
)
OWNER_ENDPOINTS = (
    "/api/inbox?limit=1",
    "/api/telegram/chats",
)
PAGES_ASSETS = (
    "/",
    "/manifest.webmanifest",
    "/service-worker.js",
    "/api-client.js",
    "/inbox-ui.js",
    "/inbox.css",
    "/release.json",
)
TELEGRAM_API_BASE = "https://api.telegram.org"
WEBHOOK_PATH = "/api/telegram/webhook"


class VerificationError(RuntimeError):
    pass


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise VerificationError(f"Environment file not found: {path}")

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def normalize_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise VerificationError("URL is not configured")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"https://{normalized}"
    return normalized


def require_env(values: dict[str, str], name: str) -> str:
    value = values.get(name, "").strip()
    if not value:
        raise VerificationError(f"{name} is not configured")
    return value


def http_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    body = None
    method = "GET"
    request_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        method = "POST"
        request_headers["Content-Type"] = "application/json"

    req = request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method,
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raise VerificationError(f"HTTP {exc.code} while checking production") from None
    except (error.URLError, TimeoutError):
        raise VerificationError("Network request failed while checking production") from None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise VerificationError("Production endpoint returned invalid JSON") from None


def fetch_asset(url: str, timeout: int = 30) -> None:
    req = request.Request(url, headers={"Accept": "*/*"}, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                raise VerificationError(f"Published asset returned HTTP {response.status}")
            if not response.read(1):
                raise VerificationError("Published asset is empty")
    except error.HTTPError as exc:
        raise VerificationError(f"Published asset returned HTTP {exc.code}") from None
    except (error.URLError, TimeoutError):
        raise VerificationError("Published asset is unavailable") from None


def validate_health(data: Any, expected_version: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise VerificationError("Health response must be a JSON object")

    actual_version = str(data.get("version") or "").strip()
    if actual_version != expected_version:
        raise VerificationError(
            f"Health version mismatch: expected {expected_version}, got {actual_version or 'empty'}"
        )

    disabled = [name for name in REQUIRED_HEALTH_FLAGS if data.get(name) is not True]
    if disabled:
        raise VerificationError(
            "Production integrations are not ready: " + ", ".join(disabled)
        )
    return data


def validate_list_endpoint(data: Any, path: str) -> int:
    if not isinstance(data, list):
        raise VerificationError(f"{path} must return a JSON list")
    return len(data)


def validate_webhook_info(
    data: Any,
    *,
    expected_url: str,
    expected_ip: str | None,
) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise VerificationError("Telegram rejected getWebhookInfo")
    info = data.get("result")
    if not isinstance(info, dict):
        raise VerificationError("Telegram returned invalid webhook information")
    if info.get("url") != expected_url:
        raise VerificationError("Telegram webhook URL does not match the current API")
    if expected_ip and info.get("ip_address") != expected_ip:
        raise VerificationError("Telegram webhook IP does not match TELEGRAM_WEBHOOK_IP")
    return info


def resolve_expected_version(explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise VerificationError("Could not determine the expected release version") from None
    version = completed.stdout.strip()
    if not version:
        raise VerificationError("Expected release version is empty")
    return version


def verify_production(env_file: Path, expected_version: str) -> dict[str, Any]:
    values = read_env(env_file)
    api_base = normalize_base_url(require_env(values, "API_DOMAIN"))
    frontend_base = normalize_base_url(
        values.get("FRONTEND_PUBLIC_URL", DEFAULT_FRONTEND_URL)
    )
    owner_key = require_env(values, "OWNER_API_KEY")
    telegram_token = require_env(values, "TELEGRAM_BOT_TOKEN")
    expected_webhook_url = f"{api_base}{WEBHOOK_PATH}"
    expected_webhook_ip = values.get("TELEGRAM_WEBHOOK_IP", "").strip() or None

    health = validate_health(
        http_json(f"{api_base}/health"),
        expected_version,
    )

    endpoint_counts: dict[str, int] = {}
    owner_headers = {"X-Owner-Key": owner_key}
    for path in OWNER_ENDPOINTS:
        endpoint_counts[path] = validate_list_endpoint(
            http_json(f"{api_base}{path}", headers=owner_headers),
            path,
        )

    webhook = validate_webhook_info(
        http_json(f"{TELEGRAM_API_BASE}/bot{telegram_token}/getWebhookInfo"),
        expected_url=expected_webhook_url,
        expected_ip=expected_webhook_ip,
    )

    checked_assets: list[str] = []
    for path in PAGES_ASSETS:
        fetch_asset(f"{frontend_base}{path}")
        checked_assets.append(path)

    return {
        "release": expected_version,
        "api": api_base,
        "frontend": frontend_base,
        "health": {
            "service": health.get("service"),
            "environment": health.get("environment"),
            "database_configured": True,
            "openai_configured": True,
            "telegram_configured": True,
        },
        "owner_endpoints": endpoint_counts,
        "telegram_webhook": {
            "url": webhook.get("url"),
            "ip_address": webhook.get("ip_address"),
            "pending_update_count": webhook.get("pending_update_count", 0),
        },
        "pages_assets": checked_assets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the deployed Bar Manager AI integration without exposing secrets."
        )
    )
    parser.add_argument(
        "--env-file",
        default=str(DEFAULT_ENV_FILE),
        help="Path to the protected FirstVDS environment file.",
    )
    parser.add_argument(
        "--expected-version",
        help="Expected 12-character release commit. Defaults to the current checkout.",
    )
    args = parser.parse_args()

    try:
        expected_version = resolve_expected_version(args.expected_version)
        result = verify_production(Path(args.env_file), expected_version)
    except VerificationError as exc:
        print(f"Production verification failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("Production integration is ready for user acceptance testing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
