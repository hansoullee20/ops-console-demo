"""Migration runner: initialisation, idempotency, backups, drift, safety."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db, migrate
from app.services.health import REQUIRED_TABLES


def test_repo_migrations_are_wellformed():
    migrations = migrate.discover_migrations()
    assert migrations, "no migration files found"
    versions = [m.version for m in migrations]
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
    assert versions[0] == 1


def test_init_creates_every_required_table(db_path: Path, backups_dir: Path):
    result = migrate.run_migrations(db_path, backups_dir=backups_dir)

    assert result.applied == [1]
    assert result.schema_version == 1
    assert db_path.exists()

    with db.connection(db_path) as conn:
        tables = set(db.table_names(conn))

    for table in REQUIRED_TABLES:
        assert table in tables, f"missing required table: {table}"
    assert "schema_migrations" in tables
    # slot <-> employee mapping is required by AI_BUILD_PLAN.md §3
    assert "terminal_slots" in tables


def test_rerun_is_idempotent(db_path: Path, backups_dir: Path):
    first = migrate.run_migrations(db_path, backups_dir=backups_dir)
    with db.connection(db_path) as conn:
        tables_before = db.table_names(conn)
        applied_before = dict(migrate.applied_migrations(conn))

    second = migrate.run_migrations(db_path, backups_dir=backups_dir)
    third = migrate.run_migrations(db_path, backups_dir=backups_dir)

    assert first.applied == [1]
    assert second.applied == []
    assert third.applied == []
    assert second.already_applied == [1]
    assert second.schema_version == 1

    with db.connection(db_path) as conn:
        assert db.table_names(conn) == tables_before
        applied_after = dict(migrate.applied_migrations(conn))

    # re-running must not rewrite migration history
    assert applied_after[1]["applied_at"] == applied_before[1]["applied_at"]
    assert applied_after[1]["checksum"] == applied_before[1]["checksum"]
    # nothing pending means nothing to back up
    assert second.backup_path is None
    assert list(backups_dir.iterdir()) == []


def test_rerun_preserves_existing_rows(migrated_db: Path, backups_dir: Path):
    with db.transaction(migrated_db) as conn:
        conn.execute(
            "INSERT INTO employees (employee_code, name, hire_date) VALUES ('E900', '보존', '2024-01-01')"
        )

    migrate.run_migrations(migrated_db, backups_dir=backups_dir)

    with db.connection(migrated_db) as conn:
        row = conn.execute("SELECT name FROM employees WHERE employee_code = 'E900'").fetchone()
    assert row["name"] == "보존"


def _write_migration(directory: Path, name: str, sql: str) -> Path:
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


def test_pending_migration_backs_up_existing_database(
    tmp_path: Path, db_path: Path, backups_dir: Path
):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(
        migrations_dir,
        "0001_base.sql",
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY, label TEXT);",
    )

    first = migrate.run_migrations(db_path, migrations_dir, backups_dir)
    assert first.backup_path is None  # nothing existed to back up

    with db.transaction(db_path) as conn:
        conn.execute("INSERT INTO widgets (label) VALUES ('keep-me')")

    _write_migration(
        migrations_dir,
        "0002_add_column.sql",
        "ALTER TABLE widgets ADD COLUMN note TEXT;",
    )
    second = migrate.run_migrations(db_path, migrations_dir, backups_dir)

    assert second.applied == [2]
    assert second.backup_path is not None
    assert second.backup_path.exists()

    # the backup holds the pre-migration schema and the original row
    with db.connection(second.backup_path) as backup:
        columns = {r[1] for r in backup.execute("PRAGMA table_info(widgets)")}
        assert "note" not in columns
        assert backup.execute("SELECT COUNT(*) FROM widgets").fetchone()[0] == 1

    # and the live database has both the new column and the original row
    with db.connection(db_path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(widgets)")}
        assert "note" in columns
        assert conn.execute("SELECT label FROM widgets").fetchone()[0] == "keep-me"


def test_checksum_drift_is_refused(tmp_path: Path, db_path: Path, backups_dir: Path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    path = _write_migration(
        migrations_dir, "0001_base.sql", "CREATE TABLE widgets (id INTEGER PRIMARY KEY);"
    )
    migrate.run_migrations(db_path, migrations_dir, backups_dir)

    path.write_text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, extra TEXT);", encoding="utf-8")

    with pytest.raises(migrate.MigrationError, match="checksum mismatch"):
        migrate.run_migrations(db_path, migrations_dir, backups_dir)


def test_database_ahead_of_code_is_refused(tmp_path: Path, db_path: Path, backups_dir: Path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_base.sql", "CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    _write_migration(migrations_dir, "0002_more.sql", "CREATE TABLE gadgets (id INTEGER PRIMARY KEY);")
    migrate.run_migrations(db_path, migrations_dir, backups_dir)

    (migrations_dir / "0002_more.sql").unlink()

    with pytest.raises(migrate.MigrationError, match="older than the database"):
        migrate.run_migrations(db_path, migrations_dir, backups_dir)


def test_destructive_migration_requires_explicit_marker(
    tmp_path: Path, db_path: Path, backups_dir: Path
):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_base.sql", "CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    migrate.run_migrations(db_path, migrations_dir, backups_dir)

    _write_migration(migrations_dir, "0002_drop.sql", "DROP TABLE widgets;")
    with pytest.raises(migrate.MigrationError, match="destructive"):
        migrate.run_migrations(db_path, migrations_dir, backups_dir)

    # the refusal must not have run anything
    with db.connection(db_path) as conn:
        assert "widgets" in db.table_names(conn)

    # opting in explicitly is allowed
    _write_migration(
        migrations_dir,
        "0002_drop.sql",
        "-- ops:allow-destructive\nDROP TABLE widgets;",
    )
    result = migrate.run_migrations(db_path, migrations_dir, backups_dir)
    assert result.applied == [2]


def test_shipped_migrations_are_not_destructive():
    for migration in migrate.discover_migrations():
        assert not migration.destructive_statements(), (
            f"{migration.path.name} contains destructive SQL"
        )


def test_failed_migration_is_atomic(tmp_path: Path, db_path: Path, backups_dir: Path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_base.sql", "CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    migrate.run_migrations(db_path, migrations_dir, backups_dir)

    _write_migration(
        migrations_dir,
        "0002_broken.sql",
        "CREATE TABLE gadgets (id INTEGER PRIMARY KEY);\nTHIS IS NOT SQL;",
    )
    with pytest.raises(migrate.MigrationError, match="rolled back"):
        migrate.run_migrations(db_path, migrations_dir, backups_dir)

    with db.connection(db_path) as conn:
        tables = db.table_names(conn)
        assert "gadgets" not in tables, "partial schema survived a failed migration"
        assert migrate.schema_version(conn) == 1


def test_badly_named_migration_file_is_refused(tmp_path: Path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "oops.sql", "SELECT 1;")
    with pytest.raises(migrate.MigrationError, match="NNNN_name.sql"):
        migrate.discover_migrations(migrations_dir)


def test_schema_version_helper(migrated_db: Path):
    with db.connection(migrated_db) as conn:
        assert migrate.schema_version(conn) == 1


def test_connections_enforce_foreign_keys(migrated_db: Path):
    with db.connection(migrated_db) as conn:
        assert db.foreign_keys_enabled(conn) is True

    # a raw sqlite3 connection does not — which is exactly why db.connect exists
    raw = sqlite3.connect(migrated_db)
    try:
        assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    finally:
        raw.close()
