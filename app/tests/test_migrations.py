"""Migration runner: initialisation, idempotency, backups, drift, safety."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app import db, migrate
from app.services.health import REQUIRED_TABLES

# Derived from the shipped migrations rather than hard-coded, so adding a
# migration does not silently invalidate these assertions.
SHIPPED_VERSIONS = [m.version for m in migrate.discover_migrations()]
LATEST_VERSION = max(SHIPPED_VERSIONS)


def test_repo_migrations_are_wellformed():
    migrations = migrate.discover_migrations()
    assert migrations, "no migration files found"
    versions = [m.version for m in migrations]
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
    assert versions[0] == 1


def test_init_creates_every_required_table(db_path: Path, backups_dir: Path):
    result = migrate.run_migrations(db_path, backups_dir=backups_dir)

    assert result.applied == SHIPPED_VERSIONS
    assert result.schema_version == LATEST_VERSION
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

    assert first.applied == SHIPPED_VERSIONS
    assert second.applied == []
    assert third.applied == []
    assert second.already_applied == SHIPPED_VERSIONS
    assert second.schema_version == LATEST_VERSION

    with db.connection(db_path) as conn:
        assert db.table_names(conn) == tables_before
        applied_after = dict(migrate.applied_migrations(conn))

    # re-running must not rewrite migration history
    for version in SHIPPED_VERSIONS:
        assert applied_after[version]["applied_at"] == applied_before[version]["applied_at"]
        assert applied_after[version]["checksum"] == applied_before[version]["checksum"]
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


def test_shipped_destructive_migrations_carry_the_marker():
    """Shipped migrations may only contain destructive SQL if they say so."""
    for migration in migrate.discover_migrations():
        if migration.destructive_statements():
            assert migration.allows_destructive, (
                f"{migration.path.name} contains destructive SQL without the "
                f"'-- {migrate.ALLOW_DESTRUCTIVE_MARKER}' marker"
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
        assert migrate.schema_version(conn) == LATEST_VERSION


def test_connections_enforce_foreign_keys(migrated_db: Path):
    with db.connection(migrated_db) as conn:
        assert db.foreign_keys_enabled(conn) is True

    # a raw sqlite3 connection does not — which is exactly why db.connect exists
    raw = sqlite3.connect(migrated_db)
    try:
        assert raw.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    finally:
        raw.close()


def test_backfilled_migration_below_applied_version_is_refused(
    tmp_path: Path, db_path: Path, backups_dir: Path
):
    """Two branches each adding a migration, one merged later: applying the
    lower version afterwards leaves hosts on the same schema_version with
    different schemas."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    _write_migration(migrations_dir, "0003_c.sql", "CREATE TABLE c (id INTEGER PRIMARY KEY);")
    assert migrate.run_migrations(db_path, migrations_dir, backups_dir).applied == [1, 3]

    _write_migration(migrations_dir, "0002_b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")
    with pytest.raises(migrate.MigrationError, match="below the applied version"):
        migrate.run_migrations(db_path, migrations_dir, backups_dir)

    with db.connection(db_path) as conn:
        assert "b" not in db.table_names(conn)

    # renumbering above the applied maximum resolves it
    (migrations_dir / "0002_b.sql").rename(migrations_dir / "0004_b.sql")
    assert migrate.run_migrations(db_path, migrations_dir, backups_dir).applied == [4]


def test_dropping_a_protective_trigger_needs_the_marker(
    tmp_path: Path, db_path: Path, backups_dir: Path
):
    """The raw-record and audit protections are triggers; removing one is as
    destructive as dropping a table."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(
        migrations_dir,
        "0001_base.sql",
        "CREATE TABLE w (id INTEGER PRIMARY KEY);\n"
        "CREATE TRIGGER guard BEFORE DELETE ON w BEGIN SELECT RAISE(ABORT, 'no'); END;\n"
        "CREATE INDEX idx_w ON w (id);",
    )
    migrate.run_migrations(db_path, migrations_dir, backups_dir)

    for sql in ("DROP TRIGGER guard;", "DROP INDEX idx_w;"):
        _write_migration(migrations_dir, "0002_unsafe.sql", sql)
        with pytest.raises(migrate.MigrationError, match="destructive"):
            migrate.run_migrations(db_path, migrations_dir, backups_dir)

    with db.connection(db_path) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger','index')")}
        assert "guard" in names and "idx_w" in names


def test_backup_is_consistent_with_an_uncheckpointed_wal(
    tmp_path: Path, db_path: Path, backups_dir: Path
):
    """The snapshot is taken through SQLite's backup API, so committed data
    still sitting in the WAL must be present in the backup."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_base.sql", "CREATE TABLE w (id INTEGER PRIMARY KEY, v TEXT);")
    migrate.run_migrations(db_path, migrations_dir, backups_dir)

    live = db.connect(db_path)
    try:
        assert live.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        for i in range(500):
            live.execute("INSERT INTO w (v) VALUES (?)", (f"row{i}",))
        live.commit()
        assert db_path.with_suffix(".db-wal").stat().st_size > 0  # uncheckpointed

        _write_migration(migrations_dir, "0002_add.sql", "ALTER TABLE w ADD COLUMN note TEXT;")
        result = migrate.run_migrations(db_path, migrations_dir, backups_dir)
    finally:
        live.close()

    assert result.backup_path is not None
    with db.connection(result.backup_path) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert backup.execute("SELECT COUNT(*) FROM w").fetchone()[0] == 500
        assert "note" not in {r[1] for r in backup.execute("PRAGMA table_info(w)")}


def test_bookkeeping_commits_atomically_with_the_schema(
    tmp_path: Path, db_path: Path, backups_dir: Path, monkeypatch
):
    """If recording the migration fails, its DDL must roll back too — otherwise
    the next start-up re-runs a migration whose schema already exists."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_a.sql", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    migrate.run_migrations(db_path, migrations_dir, backups_dir)
    _write_migration(migrations_dir, "0002_b.sql", "CREATE TABLE b (id INTEGER PRIMARY KEY);")

    class FailsToRecord(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if "INSERT INTO schema_migrations" in sql:
                raise sqlite3.OperationalError("simulated crash while recording the migration")
            return super().execute(sql, *args, **kwargs)

    def connect(path=None, *, read_only=False):
        conn = sqlite3.connect(path, factory=FailsToRecord)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    monkeypatch.setattr(migrate.db, "connect", connect)
    with pytest.raises(migrate.MigrationError, match="rolled back"):
        migrate.run_migrations(db_path, migrations_dir, backups_dir)
    monkeypatch.undo()

    with db.connection(db_path) as conn:
        assert "b" not in db.table_names(conn)
        assert migrate.schema_version(conn) == 1


def test_migration_managing_its_own_transaction_is_refused(
    tmp_path: Path, db_path: Path, backups_dir: Path
):
    """A COMMIT inside a migration commits everything before it, so a later
    failure leaves a partial schema with no schema_migrations row — and the
    migration then fails forever with "table ... already exists"."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(migrations_dir, "0001_base.sql", "CREATE TABLE base (id INTEGER PRIMARY KEY);")
    migrate.run_migrations(db_path, migrations_dir, backups_dir)

    _write_migration(
        migrations_dir,
        "0002_selfcommit.sql",
        "CREATE TABLE early (id INTEGER PRIMARY KEY);\n"
        "COMMIT;\n"
        "CREATE TABLE late (id INTEGER PRIMARY KEY);\n"
        "THIS IS NOT SQL;\n",
    )
    with pytest.raises(migrate.MigrationError, match="manages its own transaction"):
        migrate.run_migrations(db_path, migrations_dir, backups_dir)

    # refused before running: no partial schema, and the next run is not wedged
    with db.connection(db_path) as conn:
        tables = db.table_names(conn)
        assert "early" not in tables and "late" not in tables
        assert migrate.schema_version(conn) == 1


@pytest.mark.parametrize(
    "statement",
    ["BEGIN;", "BEGIN TRANSACTION;", "BEGIN IMMEDIATE TRANSACTION;", "COMMIT;",
     "END TRANSACTION;", "SAVEPOINT sp1;", "ROLLBACK;", "ROLLBACK TO sp1;"],
)
def test_every_transaction_control_form_is_refused(
    tmp_path: Path, db_path: Path, backups_dir: Path, statement: str
):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(
        migrations_dir, "0001_base.sql", f"CREATE TABLE w (id INTEGER PRIMARY KEY);\n{statement}\n"
    )
    with pytest.raises(migrate.MigrationError, match="manages its own transaction"):
        migrate.run_migrations(db_path, migrations_dir, backups_dir)


def test_trigger_bodies_are_not_mistaken_for_transaction_control(
    tmp_path: Path, db_path: Path, backups_dir: Path
):
    """CREATE TRIGGER bodies are delimited by BEGIN ... END; every shipped
    migration uses them, so the guard must not fire on them."""
    for migration in migrate.discover_migrations():
        assert migration.transaction_control_statements() == [], (
            f"{migration.path.name} falsely flagged: "
            f"{migration.transaction_control_statements()}"
        )

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_migration(
        migrations_dir,
        "0001_trigger.sql",
        "CREATE TABLE w (id INTEGER PRIMARY KEY, v TEXT);\n"
        "CREATE TRIGGER trg_w BEFORE DELETE ON w FOR EACH ROW\n"
        "BEGIN\n"
        "    SELECT RAISE(ABORT, 'no deletes');\n"
        "END;\n",
    )
    assert migrate.run_migrations(db_path, migrations_dir, backups_dir).applied == [1]


def test_0006_converts_an_existing_database_without_losing_a_punch(
    tmp_path: Path, db_path: Path, backups_dir: Path
):
    """The upgrade path for a database that already imported a month.

    Before 0006 the ordinal in a dedupe key was the punch's position in the
    cell, so a re-export containing one extra earlier punch re-imported every
    later punch as new. Fixing the rule is not enough — the keys already in the
    table have to be rewritten too, or the first re-export after the upgrade
    duplicates the month it was supposed to top up.
    """
    import shutil

    earlier = tmp_path / "migrations-0005"
    earlier.mkdir()
    for migration in migrate.discover_migrations():
        if migration.version <= 5:
            shutil.copy(migration.path, earlier / migration.path.name)

    assert migrate.run_migrations(db_path, earlier, backups_dir).schema_version == 5

    with db.transaction(db_path) as conn:
        conn.execute(
            "INSERT INTO employees (employee_code, name, zone, hire_date) "
            "VALUES ('E1', '테스트', '본관', '2024-01-01')"
        )
        conn.execute(
            "INSERT INTO import_runs (source_filename, source_kind, status) "
            "VALUES ('m.XLS', 'fingerprint_xls', 'applied')"
        )
        # written the way the pre-0006 importer wrote them
        for position, time in enumerate(["06:40", "06:40", "07:00", "16:00"]):
            conn.execute(
                "INSERT INTO punch_events (terminal_id, terminal_slot_code, punch_at,"
                " work_date, punch_type, dedupe_key, occurrence_index, import_run_id,"
                " employee_id) VALUES ('default', '001', ?, '2026-07-01', 'unknown', ?, ?, 1, 1)",
                (f"2026-07-01T{time}:00", f"default|001|2026-07-01|{time}|unknown|{position}",
                 position),
            )

    result = migrate.run_migrations(db_path, backups_dir=backups_dir)
    assert 6 in result.applied
    assert result.backup_path, "an existing database is backed up before conversion"

    with db.connection(db_path) as conn:
        rows = conn.execute(
            "SELECT substr(punch_at, 12, 5) AS t, occurrence_index, cell_position,"
            "       active_import_run_id, dedupe_key FROM punch_events ORDER BY id"
        ).fetchall()

    assert len(rows) == 4, "no punch may be lost by a migration"
    # the ordinal now counts repeats: only the two 06:40s are 0 and 1
    assert [r["occurrence_index"] for r in rows] == [0, 1, 0, 0]
    # the old meaning is preserved as provenance
    assert [r["cell_position"] for r in rows] == [0, 1, 2, 3]
    assert all(r["active_import_run_id"] == 1 for r in rows)
    # and the keys match what the parser produces now
    assert [r["dedupe_key"] for r in rows] == [
        "default|001|2026-07-01|06:40|unknown|0",
        "default|001|2026-07-01|06:40|unknown|1",
        "default|001|2026-07-01|07:00|unknown|0",
        "default|001|2026-07-01|16:00|unknown|0",
    ]
