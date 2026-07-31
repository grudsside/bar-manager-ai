from app.migrate import sql_string_literal


def test_sql_string_literal_escapes_single_quotes() -> None:
    assert sql_string_literal("001_owner's.sql") == "'001_owner''s.sql'"


def test_pooler_migration_source_avoids_parameter_placeholders() -> None:
    from pathlib import Path

    source = Path("app/migrate.py").read_text(encoding="utf-8")
    assert "statement_cache_size=0" in source
    assert "where name = $1" not in source
    assert "values ($1)" not in source
