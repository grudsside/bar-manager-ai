from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(path for path in directory.glob("*.sql") if path.is_file())


async def apply_migrations(database_url: str) -> None:
    connection = await asyncpg.connect(database_url)
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
                print(f"Migration already applied: {migration.name}")
                continue

            sql = migration.read_text(encoding="utf-8")
            async with connection.transaction():
                await connection.execute(sql)
                await connection.execute(
                    "insert into schema_migrations (name) values ($1)",
                    migration.name,
                )
            print(f"Migration applied: {migration.name}")
    finally:
        await connection.close()


async def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is not configured; database migrations skipped")
        return
    await apply_migrations(database_url)


if __name__ == "__main__":
    asyncio.run(main())
