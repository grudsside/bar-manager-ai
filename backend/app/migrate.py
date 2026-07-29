from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 20


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(path for path in directory.glob("*.sql") if path.is_file())


def describe_database_target(database_url: str) -> str:
    """Return a safe database target description without credentials."""
    try:
        parsed = urlsplit(database_url)
        host = parsed.hostname or "unknown-host"
        port = parsed.port or 5432
        database = parsed.path.lstrip("/") or "postgres"
        return f"{host}:{port}/{database}"
    except ValueError:
        return "configured PostgreSQL target"


async def apply_migrations(database_url: str) -> None:
    timeout_seconds = int(
        os.getenv("DB_CONNECT_TIMEOUT_SECONDS", str(DEFAULT_CONNECT_TIMEOUT_SECONDS))
    )
    target = describe_database_target(database_url)
    print(
        f"Connecting to PostgreSQL at {target} "
        f"(timeout {timeout_seconds}s)...",
        flush=True,
    )

    try:
        connection = await asyncio.wait_for(
            asyncpg.connect(
                database_url,
                timeout=timeout_seconds,
                command_timeout=60,
            ),
            timeout=timeout_seconds + 2,
        )
    except TimeoutError as exc:
        raise RuntimeError(
            f"Timed out connecting to PostgreSQL at {target}. "
            "Check the Supabase Session pooler host, port 5432, DNS and outbound network access."
        ) from exc

    print("PostgreSQL connection established", flush=True)
    try:
        await connection.execute(
            """
            create table if not exists schema_migrations (
                name text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )

        for migration in discover_migrations():
            already_applied = await connection.fetchval(
                "select exists(select 1 from schema_migrations where name = $1)",
                migration.name,
            )
            if already_applied:
                print(f"Migration already applied: {migration.name}", flush=True)
                continue

            sql = migration.read_text(encoding="utf-8")
            async with connection.transaction():
                await connection.execute(sql)
                await connection.execute(
                    "insert into schema_migrations (name) values ($1)",
                    migration.name,
                )
            print(f"Migration applied: {migration.name}", flush=True)
    finally:
        await connection.close()


async def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is not configured; database migrations skipped", flush=True)
        return
    await apply_migrations(database_url)


if __name__ == "__main__":
    asyncio.run(main())
