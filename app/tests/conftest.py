"""Shared test fixtures.

Every test runs against a throw-away database in a tmp directory so the real
``data/ops_console.db`` is never touched by the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import db, migrate


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "ops_console.db"


@pytest.fixture
def backups_dir(tmp_path: Path) -> Path:
    path = tmp_path / "backups"
    path.mkdir()
    return path


@pytest.fixture
def migrated_db(db_path: Path, backups_dir: Path) -> Path:
    """A database with every migration applied."""
    migrate.run_migrations(db_path, backups_dir=backups_dir)
    return db_path


@pytest.fixture
def conn(migrated_db: Path):
    connection = db.connect(migrated_db)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def employee(conn):
    """One employee to hang foreign keys off."""
    cur = conn.execute(
        "INSERT INTO employees (employee_code, name, zone, hire_date) VALUES (?, ?, ?, ?)",
        ("E001", "테스트직원", "본관 1층", "2024-01-01"),
    )
    conn.commit()
    return int(cur.lastrowid)
