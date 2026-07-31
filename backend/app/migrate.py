from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 20
DEFAULT_STATEMENT_TIMEOUT_SECONDS = 60
DEFAULT_LOCK_TIMEOUT_SECONDS = 10
_DOLLAR_QUOTE_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")


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


def split_sql_statements(sql: str) -> list[str]:
    """Split PostgreSQL SQL on semicolons outside quoted content."""
    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None

    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""

        if in_line_comment:
            buffer.append(char)
            index += 1
            if char == "\n":
                in_line_comment = False
            continue

        if in_block_comment:
            buffer.append(char)
            if char == "*" and next_char == "/":
                buffer.append(next_char)
                index += 2
                in_block_comment = False
            else:
                index += 1
            continue

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                buffer.append(char)
                index += 1
            continue

        if in_single_quote:
            buffer.append(char)
            if char == "'":
                if next_char == "'":
                    buffer.append(next_char)
                    index += 2
                    continue
                in_single_quote = False
            index += 1
            continue

        if in_double_quote:
            buffer.append(char)
            if char == '"':
                if next_char == '"':
                    buffer.append(next_char)
                    index += 2
                    continue
                in_double_quote = False
            index += 1
            continue

        if char == "-" and next_char == "-":
            buffer.extend((char, next_char))
            index += 2
            in_line_comment = True
            continue

        if char == "/" and next_char == "*":
            buffer.extend((char, next_char))
            index += 2
            in_block_comment = True
            continue

        if char == "'":
            buffer.append(char)
            index += 1
            in_single_quote = True
            continue

        if char == '"':
            buffer.append(char)
            index += 1
            in_double_quote = True
            continue

        if char == "$":
            match = _DOLLAR_QUOTE_RE.match(sql, index)
            if match:
                dollar_tag = match.group(0)
                buffer.append(dollar_tag)
                index = match.end()
                continue

        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer.clear()
            index += 1
            continue

        buffer.append(char)
        index += 1

    remaining = "".join(buffer).strip()
    if remaining:
        statements.append(remaining)

    return statements


def statement_summary(statement: str, limit: int = 120) -> str:
    compact = " ".join(statement.split())
    return compact if len(compact) <= limit else f"{compact[: limit - 3]}..."


def sql_string_literal(value: str) -> str:
    """Quote a trusted internal value as a PostgreSQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def command_status_row_count(status: str) -> int:
    """Extract the trailing row count from a PostgreSQL command tag."""
    match = re.search(r"(?:^|\s)(\d+)$", status.strip())
    return int(match.group(1)) if match else 0


async def run_step(label: str, awaitable, timeout_seconds: int):
    print(f"Starting: {label} (timeout {timeout_seconds}s)", flush=True)
    try:
        result = await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise RuntimeError(
            f"Timed out during: {label}. The database may be waiting on a lock or the SQL statement may be incompatible."
        ) from exc
    print(f"Completed: {label}", flush=True)
    return result


async def apply_migrations(database_url: str) -> None:
    connect_timeout = int(
        os.getenv("DB_CONNECT_TIMEOUT_SECONDS", str(DEFAULT_CONNECT_TIMEOUT_SECONDS))
    )
    statement_timeout = int(
        os.getenv("DB_STATEMENT_TIMEOUT_SECONDS", str(DEFAULT_STATEMENT_TIMEOUT_SECONDS))
    )
    lock_timeout = int(
        os.getenv("DB_LOCK_TIMEOUT_SECONDS", str(DEFAULT_LOCK_TIMEOUT_SECONDS))
    )
    target = describe_database_target(database_url)
    print(
        f"Connecting to PostgreSQL at {target} "
        f"(timeout {connect_timeout}s)...",
        flush=True,
    )

    try:
        connection = await asyncio.wait_for(
            asyncpg.connect(
                database_url,
                timeout=connect_timeout,
                command_timeout=statement_timeout + 10,
                statement_cache_size=0,
            ),
            timeout=connect_timeout + 2,
        )
    except TimeoutError as exc:
        raise RuntimeError(
            f"Timed out connecting to PostgreSQL at {target}. "
            "Check the Supabase connection host, port, DNS and outbound network access."
        ) from exc

    print("PostgreSQL connection established", flush=True)
    try:
        await run_step(
            "configure statement_timeout",
            connection.execute(f"set statement_timeout = '{statement_timeout}s'"),
            statement_timeout,
        )
        await run_step(
            "configure lock_timeout",
            connection.execute(f"set lock_timeout = '{lock_timeout}s'"),
            statement_timeout,
        )
        await run_step(
            "prepare schema_migrations table",
            connection.execute(
                """
                create table if not exists schema_migrations (
                    name text primary key,
                    applied_at timestamptz not null default now()
                )
                """
            ),
            statement_timeout,
        )

        migrations = discover_migrations()
        print(f"Discovered {len(migrations)} migration(s)", flush=True)
        for migration in migrations:
            migration_literal = sql_string_literal(migration.name)
            check_status = await run_step(
                f"check migration {migration.name}",
                connection.execute(
                    "select 1 from schema_migrations "
                    f"where name = {migration_literal} limit 1"
                ),
                statement_timeout,
            )
            if command_status_row_count(check_status) > 0:
                print(f"Migration already applied: {migration.name}", flush=True)
                continue

            sql = migration.read_text(encoding="utf-8")
            statements = split_sql_statements(sql)
            print(
                f"Applying migration: {migration.name} "
                f"({len(sql.encode('utf-8'))} bytes, {len(statements)} statements)",
                flush=True,
            )

            # Execute statements independently through PostgreSQL's simple query
            # protocol. This avoids prepared statements and long-lived transactions
            # when migrations run through a Supabase pooler.
            for position, statement in enumerate(statements, start=1):
                label = (
                    f"execute {migration.name} statement "
                    f"{position}/{len(statements)}: {statement_summary(statement)}"
                )
                await run_step(
                    label,
                    connection.execute(statement),
                    statement_timeout + 5,
                )

            await run_step(
                f"record migration {migration.name}",
                connection.execute(
                    "insert into schema_migrations (name) "
                    f"values ({migration_literal}) on conflict (name) do nothing"
                ),
                statement_timeout,
            )
            print(f"Migration applied: {migration.name}", flush=True)
    finally:
        await connection.close()


async def main() -> None:
    database_url = os.getenv("MIGRATION_DATABASE_URL", "").strip()
    if not database_url:
        database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is not configured; database migrations skipped", flush=True)
        return
    await apply_migrations(database_url)


if __name__ == "__main__":
    asyncio.run(main())
