from pathlib import Path

from app.migrate import discover_migrations, describe_database_target


def test_migrations_are_discoverable_and_ordered() -> None:
    migrations = discover_migrations()
    assert migrations, "At least one SQL migration must exist"
    assert migrations == sorted(migrations)
    assert all(path.suffix == ".sql" for path in migrations)


def test_database_target_description_hides_credentials() -> None:
    description = describe_database_target(
        "postgresql://secret-user:secret-password@example.pooler.supabase.com:5432/postgres?sslmode=require"
    )
    assert description == "example.pooler.supabase.com:5432/postgres"
    assert "secret" not in description
