from app.migrate import discover_migrations


def test_initial_migration_is_discoverable() -> None:
    migrations = discover_migrations()
    assert migrations
    assert migrations[0].name == "001_initial.sql"
    assert "create table if not exists tasks" in migrations[0].read_text(encoding="utf-8").lower()
