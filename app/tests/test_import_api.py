"""The fingerprint XLS import over HTTP.

These are the first mutation endpoints in the console, so the tests are about
what a tired operator can and cannot do by accident:

  * a preview must change nothing at all
  * applying must need a second, explicit request carrying the preview's token
  * a rollback must not delete a punch or undo somebody's manual correction
  * a real export must not land in a database full of invented people

The fixtures are generated at run time from fictional data; the real export
contains employee names and is never committed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import create_app
from app.seed.demo_dataset import seed_demo_database
from app.tests.fixtures.terminal_xls import build_export, realistic_month

ENDPOINT = "/api/v1/imports"


@pytest.fixture
def export(tmp_path: Path) -> Path:
    return build_export(tmp_path / "2026-07.XLS", slots=realistic_month())


def _paths(monkeypatch, database: Path, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "DB_PATH", database)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "ALLOW_DEMO_IMPORT", False)


@pytest.fixture
def operational_db(migrated_db: Path) -> Path:
    """A database with real staff in it, as far as the app is concerned.

    The people are the fictional seed — the point of this fixture is the
    data_context marker, which is what separates an operational database from
    the demo one.
    """
    seed_demo_database(migrated_db)
    conn = db.connect(migrated_db)
    try:
        conn.execute("UPDATE app_meta SET value = 'operational' WHERE key = 'data_context'")
        conn.commit()
    finally:
        conn.close()
    return migrated_db


@pytest.fixture
def client(monkeypatch, operational_db: Path, tmp_path: Path):
    _paths(monkeypatch, operational_db, tmp_path)
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def demo_client(monkeypatch, migrated_db: Path, tmp_path: Path):
    """The same app over a demo-seeded database."""
    seed_demo_database(migrated_db)
    _paths(monkeypatch, migrated_db, tmp_path)
    with TestClient(create_app()) as c:
        yield c


def _upload(client, export: Path, name: str = "2026-07.XLS"):
    with export.open("rb") as handle:
        return client.post(ENDPOINT, files={"file": (name, handle, "application/vnd.ms-excel")})


def _counts(database: Path) -> dict:
    conn = db.connect(database)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("punch_events", "attendance_days", "audit_log", "import_run_days")
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------
def test_preview_writes_no_business_data(client, export: Path, operational_db: Path):
    before = _counts(operational_db)
    body = _upload(client, export).json()

    assert body["newPunches"] > 0
    assert body["canApply"] is True
    assert body["confirmationToken"]
    assert body["periodStart"] == "2026-07-01"

    after = _counts(operational_db)
    assert after["punch_events"] == before["punch_events"]
    assert after["attendance_days"] == before["attendance_days"]
    assert after["import_run_days"] == before["import_run_days"]


def test_preview_opens_the_import_run_before_parsing(client, export: Path):
    """The run exists from the upload, so even an attempt leaves a record."""
    run_id = _upload(client, export).json()["importRunId"]
    detail = client.get(f"{ENDPOINT}/{run_id}").json()
    assert detail["status"] == "previewed"
    assert detail["sourceFilename"] == "2026-07.XLS"
    assert detail["sourceSha256"]


def test_a_file_that_cannot_be_parsed_records_the_attempt(client, tmp_path: Path):
    junk = tmp_path / "not-an-export.xls"
    junk.write_bytes(b"this is not a workbook")

    response = _upload(client, junk, name="not-an-export.xls")
    assert response.status_code == 422

    runs = client.get(ENDPOINT).json()
    assert runs[0]["status"] == "failed"
    assert runs[0]["errorMessage"]


def test_a_non_xls_upload_is_refused_by_name(client, tmp_path: Path):
    other = tmp_path / "attendance.xlsx"
    other.write_bytes(b"PK\x03\x04")
    response = _upload(client, other, name="attendance.xlsx")
    assert response.status_code == 415
    assert client.get(ENDPOINT).json() == []       # no run opened for a wrong file


def test_an_oversized_upload_is_refused(monkeypatch, client, export: Path):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 1024)
    assert _upload(client, export).status_code == 413


def test_an_odd_filename_cannot_escape_the_uploads_directory(client, export: Path, tmp_path: Path):
    body = _upload(client, export, name="../../index.html.xls").json()
    detail = client.get(f"{ENDPOINT}/{body['importRunId']}/source").json()
    stored = Path(detail["storedPath"]).resolve()
    assert stored.is_relative_to((tmp_path / "uploads").resolve())
    assert detail["exists"] is True


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------
def test_apply_without_the_right_token_changes_nothing(client, export: Path, operational_db: Path):
    preview = _upload(client, export).json()
    before = _counts(operational_db)

    response = client.post(
        f"{ENDPOINT}/{preview['importRunId']}/apply",
        json={"confirmationToken": "0" * 64},
    )
    assert response.status_code == 409
    assert _counts(operational_db) == before


def test_apply_writes_punches_attendance_coverage_and_audit(client, export: Path, operational_db: Path):
    preview = _upload(client, export).json()
    result = client.post(
        f"{ENDPOINT}/{preview['importRunId']}/apply",
        json={"confirmationToken": preview["confirmationToken"]},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["inserted"] == preview["newPunches"]
    assert body["attendanceRows"] > 0
    assert Path(body["snapshotPath"]).exists()      # a pre-apply snapshot was taken

    run_id = preview["importRunId"]
    conn = db.connect(operational_db)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM punch_events WHERE import_run_id = ?", (run_id,)
        ).fetchone()[0] == body["inserted"]
        # provenance survived the round trip
        row = conn.execute(
            "SELECT source_sheet, source_cell, occurrence_index FROM punch_events "
            " WHERE import_run_id = ? LIMIT 1", (run_id,)
        ).fetchone()
        assert row["source_sheet"] == "근태기록"
        assert row["source_cell"] and row["occurrence_index"] is not None
        # the audit entry carries the token the operator confirmed with
        audit = conn.execute(
            "SELECT * FROM audit_log WHERE action = 'import.apply'"
        ).fetchone()
        assert audit["confirmation_token"] == preview["confirmationToken"]
        # coverage is recorded as a fact about the file, never as an absence
        statuses = dict(
            conn.execute(
                "SELECT coverage_status, COUNT(*) FROM import_run_days GROUP BY coverage_status"
            ).fetchall()
        )
        assert statuses["reported_zero"] > 0
        assert not conn.execute(
            "SELECT 1 FROM attendance_days WHERE status = 'absent'"
        ).fetchone()
    finally:
        conn.close()


def test_a_run_can_only_be_applied_once(client, export: Path):
    preview = _upload(client, export).json()
    payload = {"confirmationToken": preview["confirmationToken"]}
    assert client.post(f"{ENDPOINT}/{preview['importRunId']}/apply", json=payload).status_code == 200
    second = client.post(f"{ENDPOINT}/{preview['importRunId']}/apply", json=payload)
    assert second.status_code == 409
    assert "applied" in second.json()["detail"]


def test_reimporting_the_same_file_adds_nothing(client, export: Path, operational_db: Path):
    first = _upload(client, export).json()
    client.post(f"{ENDPOINT}/{first['importRunId']}/apply",
                json={"confirmationToken": first["confirmationToken"]})
    total = _counts(operational_db)["punch_events"]

    second = _upload(client, export).json()
    assert second["newPunches"] == 0
    assert second["canApply"] is False
    assert _counts(operational_db)["punch_events"] == total


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------
def test_rollback_marks_punches_and_deletes_none(client, export: Path, operational_db: Path):
    preview = _upload(client, export).json()
    run_id = preview["importRunId"]
    client.post(f"{ENDPOINT}/{run_id}/apply",
                json={"confirmationToken": preview["confirmationToken"]})
    before = _counts(operational_db)["punch_events"]
    imported = preview["newPunches"]

    body = client.post(f"{ENDPOINT}/{run_id}/rollback",
                       json={"reason": "잘못된 파일을 가져왔습니다"}).json()
    assert body["punchesDeleted"] == 0
    assert body["punchesMarkedRolledBack"] == imported

    conn = db.connect(operational_db)
    try:
        # every raw event is still there, only marked
        assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == before
        assert not conn.execute(
            "SELECT 1 FROM attendance_days WHERE status = 'normal' AND source = 'fingerprint'"
            "   AND last_import_run_id = ?", (run_id,)
        ).fetchone()
        assert conn.execute(
            "SELECT reason FROM audit_log WHERE action = 'import.rollback'"
        ).fetchone()["reason"] == "잘못된 파일을 가져왔습니다"
    finally:
        conn.close()


def test_a_rollback_needs_a_reason(client, export: Path):
    preview = _upload(client, export).json()
    client.post(f"{ENDPOINT}/{preview['importRunId']}/apply",
                json={"confirmationToken": preview["confirmationToken"]})
    response = client.post(f"{ENDPOINT}/{preview['importRunId']}/rollback", json={"reason": ""})
    assert response.status_code == 422    # rejected before it reaches the service


def test_rollback_does_not_undo_a_manual_correction(client, export: Path, operational_db: Path):
    from app.services import attendance

    preview = _upload(client, export).json()
    run_id = preview["importRunId"]
    client.post(f"{ENDPOINT}/{run_id}/apply",
                json={"confirmationToken": preview["confirmationToken"]})

    conn = db.connect(operational_db)
    try:
        row = conn.execute(
            "SELECT id, employee_id, work_date FROM attendance_days "
            " WHERE last_import_run_id = ? AND status = 'normal' ORDER BY id LIMIT 1",
            (run_id,),
        ).fetchone()
        attendance.correct_attendance(
            conn,
            employee_id=row["employee_id"],
            work_date=row["work_date"],
            changes={"status": "leave"},
            actor_id="manager",
            reason="본인 확인 후 연차 처리",
        )
        conn.commit()
    finally:
        conn.close()

    body = client.post(f"{ENDPOINT}/{run_id}/rollback",
                       json={"reason": "재가져오기"}).json()
    assert body["conflicts"], "a manually corrected row must be reported, not overwritten"

    conn = db.connect(operational_db)
    try:
        assert conn.execute(
            "SELECT status FROM attendance_days WHERE id = ?", (row["id"],)
        ).fetchone()["status"] == "leave"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# the demo database
# ---------------------------------------------------------------------------
def test_import_is_refused_on_a_demo_seeded_database(demo_client, export: Path):
    response = _upload(demo_client, export)
    assert response.status_code == 409
    assert "데모" in response.json()["detail"]
    assert demo_client.get(ENDPOINT).json() == []


def test_the_demo_refusal_can_be_overridden_only_on_purpose(monkeypatch, demo_client, export: Path):
    monkeypatch.setattr(config, "ALLOW_DEMO_IMPORT", True)
    assert _upload(demo_client, export).status_code == 200


# ---------------------------------------------------------------------------
# history, and what is never served
# ---------------------------------------------------------------------------
def test_history_lists_runs_newest_first(client, export: Path):
    _upload(client, export)
    _upload(client, export)
    runs = client.get(ENDPOINT).json()
    assert [r["id"] for r in runs] == sorted((r["id"] for r in runs), reverse=True)
    assert runs[0]["sourceFilename"] == "2026-07.XLS"


def test_the_preserved_original_is_located_but_never_downloaded(client, export: Path):
    run_id = _upload(client, export).json()["importRunId"]
    response = client.get(f"{ENDPOINT}/{run_id}/source")
    assert response.status_code == 200
    assert set(response.json()) == {"sourceFilename", "storedPath", "exists", "sha256"}
    assert "application/vnd.ms-excel" not in response.headers.get("content-type", "")


def test_import_ui_is_served_and_the_buttons_are_wired(client):
    """The import flow ships as a served asset, not an inert file on disk."""
    script = client.get("/import-ui.js")
    assert script.status_code == 200
    for hook in ("OPS_OPEN_IMPORT", "OPS_IMPORT_PREVIEW", "OPS_IMPORT_APPLY",
                 "OPS_IMPORT_ROLLBACK", "OPS_OPEN_IMPORT_HISTORY"):
        assert f"window.{hook} =" in script.text

    html = client.get("/").text
    assert "OPS_OPEN_IMPORT()" in html
    assert "OPS_OPEN_IMPORT_HISTORY()" in html
    assert './import-ui.js' in html
