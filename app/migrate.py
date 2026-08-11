"""Idempotent, backed-up SQL migration runner.

Rules from AI_BUILD_PLAN.md §5 / §7 Phase 1:

* migrations must be idempotent — re-running applies nothing and never errors
* migrations must be backed up — an existing database is snapshotted before any
  pending migration touches it
* migrations must not be silently destructive — a migration containing DROP /
  DELETE / destructive ALTER is refused unless it explicitly opts in with the
  marker comment ``-- ops:allow-destructive``
* drift is detected — an already-applied migration whose file has since changed
  aborts the run instead of producing an undefined schema

Migration files live in ``app/migrations`` and are named ``NNNN_name.sql``.
They are applied in ascending numeric order, each inside one transaction, and
recorded in ``schema_migrations`` with a checksum.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app import config, db

MIGRATION_FILENAME_RE = re.compile(r"^(\d{4})_([A-Za-z0-9_\-]+)\.sql$")

ALLOW_DESTRUCTIVE_MARKER = "ops:allow-destructive"

_DESTRUCTIVE_PATTERNS = (
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
)

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
)
"""


class MigrationError(RuntimeError):
    """Raised when migrations cannot be applied safely."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    @property
    def allows_destructive(self) -> bool:
        return ALLOW_DESTRUCTIVE_MARKER in self.sql

    def destructive_statements(self) -> list[str]:
        # Strip line comments so the marker/doc text is not mistaken for SQL.
        code = "\n".join(line.split("--", 1)[0] for line in self.sql.splitlines())
        found: list[str] = []
        for pattern in _DESTRUCTIVE_PATTERNS:
            found.extend(match.group(0) for match in pattern.finditer(code))
        return found


@dataclass
class MigrationResult:
    applied: list[int] = field(default_factory=list)
    already_applied: list[int] = field(default_factory=list)
    backup_path: Path | None = None

    @property
    def schema_version(self) -> int:
        versions = self.applied + self.already_applied
        return max(versions) if versions else 0


def discover_migrations(migrations_dir: Path | str | None = None) -> list[Migration]:
    """Load migration files in ascending version order."""
    directory = Path(migrations_dir) if migrations_dir is not None else config.MIGRATIONS_DIR
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")

    migrations: dict[int, Migration] = {}
    for path in sorted(directory.iterdir()):
        if path.suffix != ".sql" or not path.is_file():
            continue
        match = MIGRATION_FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(
                f"migration file does not match NNNN_name.sql: {path.name}"
            )
        version = int(match.group(1))
        if version in migrations:
            raise MigrationError(
                f"duplicate migration version {version:04d}: "
                f"{migrations[version].path.name} and {path.name}"
            )
        migrations[version] = Migration(
            version=version,
            name=match.group(2),
            path=path,
            sql=path.read_text(encoding="utf-8"),
        )
    return [migrations[v] for v in sorted(migrations)]


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA_MIGRATIONS_DDL)
    conn.commit()


def applied_migrations(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    _ensure_schema_migrations(conn)
    rows = conn.execute(
        "SELECT version, name, checksum, applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()
    return {row["version"]: row for row in rows}


def schema_version(conn: sqlite3.Connection) -> int:
    _ensure_schema_migrations(conn)
    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def _has_user_data_tables(conn: sqlite3.Connection) -> bool:
    """True when the database already holds tables other than the bookkeeping one."""
    return any(name != "schema_migrations" for name in db.table_names(conn))


def _backup_database(db_path: Path, backups_dir: Path, label: str) -> Path:
    """Snapshot the database with SQLite's backup API (WAL-safe)."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    target = backups_dir / f"{db_path.stem}-pre-{label}-{stamp}.db"

    source = db.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def _validate(migrations: list[Migration], applied: dict[int, sqlite3.Row]) -> None:
    known = {m.version for m in migrations}

    for version, row in applied.items():
        if version not in known:
            raise MigrationError(
                f"database is at migration {version:04d} but no such migration file exists; "
                "the code is older than the database"
            )

    for migration in migrations:
        row = applied.get(migration.version)
        if row is not None and row["checksum"] != migration.checksum:
            raise MigrationError(
                f"migration {migration.version:04d}_{migration.name}.sql changed after it was "
                "applied (checksum mismatch); write a new migration instead of editing history"
            )
        if row is None:
            destructive = migration.destructive_statements()
            if destructive and not migration.allows_destructive:
                raise MigrationError(
                    f"migration {migration.path.name} contains destructive statements "
                    f"({', '.join(sorted(set(destructive)))}); add the "
                    f"'-- {ALLOW_DESTRUCTIVE_MARKER}' marker to confirm this is intended"
                )


def run_migrations(
    db_path: Path | str | None = None,
    migrations_dir: Path | str | None = None,
    backups_dir: Path | str | None = None,
) -> MigrationResult:
    """Apply every pending migration. Safe to call on every start-up."""
    path = Path(db_path) if db_path is not None else config.DB_PATH
    backups = Path(backups_dir) if backups_dir is not None else config.BACKUPS_DIR
    migrations = discover_migrations(migrations_dir)

    path.parent.mkdir(parents=True, exist_ok=True)
    result = MigrationResult()

    conn = db.connect(path)
    try:
        applied = applied_migrations(conn)
        _validate(migrations, applied)

        pending = [m for m in migrations if m.version not in applied]
        result.already_applied = sorted(applied)
        if not pending:
            return result

        # Back up before touching a database that already holds data.
        if _has_user_data_tables(conn):
            conn.commit()
            result.backup_path = _backup_database(
                path, backups, label=f"{pending[0].version:04d}"
            )

        for migration in pending:
            # executescript() commits any pending transaction and then runs the
            # script as written, and sqlite3 does not open transactions for DDL
            # on its own. The explicit BEGIN is what makes a migration atomic:
            # a failure half-way through leaves no partial schema behind.
            try:
                conn.executescript("BEGIN;\n" + migration.sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (?, ?, ?)",
                    (migration.version, migration.name, migration.checksum),
                )
                conn.commit()
            except sqlite3.Error as exc:
                conn.rollback()
                raise MigrationError(
                    f"migration {migration.path.name} failed and was rolled back: {exc}"
                ) from exc
            result.applied.append(migration.version)
    finally:
        conn.close()

    return result


def init_database(
    db_path: Path | str | None = None,
    migrations_dir: Path | str | None = None,
    backups_dir: Path | str | None = None,
) -> MigrationResult:
    """Create runtime directories and bring the database up to date."""
    if db_path is None:
        config.ensure_runtime_dirs()
    return run_migrations(db_path, migrations_dir, backups_dir)


def _main() -> int:  # pragma: no cover - CLI convenience
    result = init_database()
    if result.applied:
        print(f"applied migrations: {', '.join(f'{v:04d}' for v in result.applied)}")
    else:
        print("database already up to date")
    if result.backup_path:
        print(f"backup written: {result.backup_path}")
    print(f"schema version: {result.schema_version:04d}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
