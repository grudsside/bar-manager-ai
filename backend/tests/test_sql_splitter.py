from app.migrate import split_sql_statements


def test_split_sql_statements_preserves_plpgsql_body() -> None:
    sql = """
    create table if not exists example (id integer);

    create or replace function touch_row()
    returns trigger language plpgsql as $$
    begin
        new.id = 1;
        return new;
    end;
    $$;

    create trigger example_touch before update on example
    for each row execute function touch_row();
    """

    statements = split_sql_statements(sql)

    assert len(statements) == 3
    assert statements[0].startswith("create table")
    assert "new.id = 1;" in statements[1]
    assert statements[2].startswith("create trigger")


def test_split_sql_statements_ignores_semicolons_in_strings_and_comments() -> None:
    sql = """
    -- comment with ; semicolon
    insert into example values ('a;b');
    /* another ; comment */
    select \"semi;colon\";
    """

    statements = split_sql_statements(sql)

    assert len(statements) == 2
    assert "'a;b'" in statements[0]
    assert '"semi;colon"' in statements[1]
