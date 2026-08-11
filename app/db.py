"""SQLite connection handling.

SQLite disables foreign key enforcement per connection by default, so every
connection created here turns it on explicitly (AI_BUILD_PLAN.md §7 Phase 1:
"foreign keys enabled"). Opening a connection any other way is a bug.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app import config


def connect(db_path: Path | str | None = None, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a configured SQLite connection.

    Foreign keys are enforced, WAL is used for concurrent readers, and a busy
    timeout avoids immediate "database is locked" failures.
    """
    path = Path(db_path) if db_path is not None else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if not read_only:
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connection(db_path: Path | str | None = None, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
    """Context-managed connection that always closes."""
    conn = connect(db_path, read_only=read_only)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Context-managed write transaction: commit on success, rollback on error."""
    conn = connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def foreign_keys_enabled(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]
