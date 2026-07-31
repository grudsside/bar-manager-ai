from pathlib import Path


def test_initial_migration_uses_builtin_uuid_function() -> None:
    sql = Path("migrations/001_initial.sql").read_text(encoding="utf-8").lower()
    assert "gen_random_uuid()" in sql
    assert "create extension" not in sql
    assert "pgcrypto" not in sql
