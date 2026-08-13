"""Health endpoint and health service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db, migrate
from app.main import create_app
from app.services import health as health_service

LATEST_VERSION = max(m.version for m in migrate.discover_migrations())


@pytest.fixture
def app_client(monkeypatch, migrated_db: Path, tmp_path: Path):
    """Point the whole app at the throw-away database."""
    monkeypatch.setattr(config, "DB_PATH", migrated_db)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    with TestClient(create_app()) as client:
        yield client


def test_health_reports_ready_database(app_client):
    response = app_client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "ops-console-backend"
    assert body["phase"] == 4
    assert body["database"]["reachable"] is True
    assert body["database"]["foreign_keys_enforced"] is True
    assert body["database"]["schema_version"] == LATEST_VERSION
    assert body["database"]["missing_tables"] == []


def test_health_reports_fingerprint_source_freshness(app_client, migrated_db: Path):
    """§3: never imply fingerprint data is live — always expose the last sync."""
    body = app_client.get("/health").json()
    assert body["fingerprint"]["last_import_at"] is None
    assert body["fingerprint"]["is_stale"] is True

    recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with db.transaction(migrated_db) as conn:
        conn.execute(
            """
            INSERT INTO import_runs (source_filename, source_kind, status, period_start,
                                     period_end, finished_at)
            VALUES ('2026-08.XLS', 'fingerprint_xls', 'applied', '2026-08-01', '2026-08-31', ?)
            """,
            (recent,),
        )

    fingerprint = app_client.get("/health").json()["fingerprint"]
    assert fingerprint["last_import_at"] == recent
    assert fingerprint["source_filename"] == "2026-08.XLS"
    assert fingerprint["period_end"] == "2026-08-31"
    assert fingerprint["is_stale"] is False


def test_old_import_is_reported_stale(migrated_db: Path):
    old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with db.transaction(migrated_db) as conn:
        conn.execute(
            """
            INSERT INTO import_runs (source_filename, source_kind, status, finished_at)
            VALUES ('2026-06.XLS', 'fingerprint_xls', 'applied', ?)
            """,
            (old,),
        )

    fingerprint = health_service.health_report(migrated_db)["fingerprint"]
    assert fingerprint["last_import_at"] == old
    assert fingerprint["is_stale"] is True


def test_unapplied_import_does_not_count_as_synced(migrated_db: Path):
    recent = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    with db.transaction(migrated_db) as conn:
        conn.execute(
            """
            INSERT INTO import_runs (source_filename, source_kind, status, finished_at)
            VALUES ('2026-08.XLS', 'fingerprint_xls', 'previewed', ?)
            """,
            (recent,),
        )
    fingerprint = health_service.health_report(migrated_db)["fingerprint"]
    assert fingerprint["last_import_at"] is None
    assert fingerprint["is_stale"] is True


def test_health_degrades_when_database_is_absent(tmp_path: Path):
    report = health_service.health_report(tmp_path / "missing.db")
    assert report["status"] == "degraded"
    assert "does not exist" in report["detail"]
    assert report["database"]["exists"] is False
    assert report["database"]["schema_version"] == 0
    # a health check must not create the database it is reporting on
    assert not (tmp_path / "missing.db").exists()


def test_health_degrades_when_schema_is_missing(tmp_path: Path):
    empty = tmp_path / "empty.db"
    db.connect(empty).close()  # exists but never migrated

    report = health_service.health_report(empty)
    assert report["status"] == "degraded"
    assert "employees" in report["detail"]
    assert report["database"]["reachable"] is True
    assert report["database"]["schema_version"] == 0
    assert set(report["database"]["missing_tables"]) == set(health_service.REQUIRED_TABLES)


def test_health_endpoint_returns_503_when_degraded(monkeypatch, tmp_path: Path):
    empty = tmp_path / "empty.db"
    monkeypatch.setattr(config, "DB_PATH", empty)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "MIGRATIONS_DIR", tmp_path / "no-migrations")

    with TestClient(create_app()) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] in {"degraded", "error"}


def test_startup_migrates_the_database(monkeypatch, tmp_path: Path):
    """Starting the app on a fresh host must create the database."""
    fresh = tmp_path / "data" / "ops_console.db"
    monkeypatch.setattr(config, "DB_PATH", fresh)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")

    assert not fresh.exists()
    with TestClient(create_app()) as client:
        body = client.get("/health").json()

    assert fresh.exists()
    assert body["status"] == "ok"
    assert body["database"]["schema_version"] == LATEST_VERSION
    with db.connection(fresh) as conn:
        assert migrate.schema_version(conn) == LATEST_VERSION


def test_the_write_surface_is_deliberately_scoped():
    """Phase 4.25 adds only its reviewed operational safety flows."""
    schema = create_app().openapi()["paths"]
    assert "/health" in schema
    assert "/api/v1/bootstrap" in schema

    writable = {
        path for path, operations in schema.items()
        for method in operations
        if method.lower() not in {"get", "head", "options"}
    }
    allowed_prefixes = (
        "/api/v1/imports", "/api/v1/terminal-slots",
        "/api/v1/leave-operations", "/api/v1/replacement-operations",
        "/api/v1/operations/exceptions", "/api/v1/attendance/manual-adjustments",
        "/api/v1/employees/",
    )
    assert writable and all(path.startswith(allowed_prefixes) for path in writable), (
        f"a write endpoint outside the operational flows: {sorted(writable)}"
    )
    assert "/api/v1/attendance" in schema
