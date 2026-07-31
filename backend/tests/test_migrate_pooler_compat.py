from pathlib import Path

from app.migrate import command_status_row_count, sql_string_literal


def test_sql_string_literal_escapes_single_quotes() -> None:
    assert sql_string_literal("001_owner's.sql") == "'001_owner''s.sql'"


def test_command_status_row_count() -> None:
    assert command_status_row_count("SELECT 0") == 0
    assert command_status_row_count("SELECT 1") == 1
    assert command_status_row_count("INSERT 0 1") == 1
    assert command_status_row_count("CREATE TABLE") == 0


def test_pooler_migration_source_uses_simple_protocol_only() -> None:
    source = Path("app/migrate.py").read_text(encoding="utf-8")
    assert "statement_cache_size=0" in source
    assert "connection.fetch(" not in source
    assert "connection.fetchval(" not in source
    assert "where name = $1" not in source
    assert "values ($1)" not in source


def test_initial_migration_triggers_are_repeatable() -> None:
    sql = Path("migrations/001_initial.sql").read_text(encoding="utf-8")
    assert sql.count("drop trigger if exists") == 4
