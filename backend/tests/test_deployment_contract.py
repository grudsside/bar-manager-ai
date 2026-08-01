from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_api_container_does_not_run_migrations_on_startup() -> None:
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "python -m app.migrate" not in dockerfile
    assert "uvicorn app.main:app" in dockerfile


def test_deploy_runs_migrations_as_separate_job() -> None:
    deploy_script = (
        REPO_ROOT / "deploy" / "firstvds" / "scripts" / "deploy.sh"
    ).read_text(encoding="utf-8")
    assert "run --rm --no-deps api python -m app.migrate" in deploy_script
    assert "timeout 300s" in deploy_script


def test_deploy_only_ignores_pooler_timeout_after_all_migrations_finish() -> None:
    deploy_script = (
        REPO_ROOT / "deploy" / "firstvds" / "scripts" / "deploy.sh"
    ).read_text(encoding="utf-8")
    assert "Migration (already applied|applied)" in deploy_script
    assert "completed_count == migration_count" in deploy_script
    assert "migration_status == 124" in deploy_script
    assert "grep -q '^TimeoutError$'" in deploy_script
    assert "Database migration failed" in deploy_script


def test_migrator_avoids_long_lived_pooler_transaction() -> None:
    migrator = (REPO_ROOT / "backend" / "app" / "migrate.py").read_text(
        encoding="utf-8"
    )
    assert "connection.transaction" not in migrator
    assert "MIGRATION_DATABASE_URL" in migrator
