"""The folder watch: automatic previewing, never automatic applying.

The terminal's PC program can export each month into a fixed folder. The
watcher reads what lands there so nobody has to remember to upload it — but the
judgement stays with a person, because a partial export that imported itself
would show a whole site as absent with nobody in the loop.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import create_app
from app.seed.demo_dataset import seed_demo_database
from app.services import import_watch
from app.tests.fixtures.terminal_xls import SlotSpec, build_export, realistic_month


@pytest.fixture
def watch_dir(tmp_path: Path) -> Path:
    path = tmp_path / "terminal-export"
    path.mkdir()
    return path


@pytest.fixture
def operational_db(migrated_db: Path) -> Path:
    seed_demo_database(migrated_db)
    conn = db.connect(migrated_db)
    try:
        conn.execute("UPDATE app_meta SET value = 'operational' WHERE key = 'data_context'")
        conn.commit()
    finally:
        conn.close()
    return migrated_db


@pytest.fixture
def watcher(monkeypatch, operational_db: Path, watch_dir: Path, tmp_path: Path):
    monkeypatch.setattr(config, "DB_PATH", operational_db)
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "ALLOW_DEMO_IMPORT", False)
    return import_watch.FolderWatcher(watch_dir, db_path=operational_db)


def _drop(watch_dir: Path, name: str = "2026-07.XLS", **kwargs) -> Path:
    return build_export(watch_dir / name, slots=kwargs.pop("slots", realistic_month()), **kwargs)


def _settle(path: Path) -> None:
    """Make the file look unchanged since the previous pass."""
    os.utime(path, (1_700_000_000, 1_700_000_000))


def _counts(database: Path) -> dict:
    conn = db.connect(database)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("punch_events", "attendance_days", "import_runs")
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# stability
# ---------------------------------------------------------------------------
def test_a_file_is_not_read_on_the_pass_that_discovers_it(watcher, watch_dir: Path):
    """A file still being written must not be parsed as a short month."""
    _drop(watch_dir)
    first = watcher.scan_once()
    assert first.previewed == []
    assert first.skipped_unstable == 1

    second = watcher.scan_once()
    assert len(second.previewed) == 1


def test_a_file_that_keeps_changing_is_left_alone(watcher, watch_dir: Path):
    path = _drop(watch_dir)
    watcher.scan_once()
    path.write_bytes(path.read_bytes() + b"\0")     # still being written
    result = watcher.scan_once()
    assert result.previewed == []
    assert result.skipped_unstable == 1


# ---------------------------------------------------------------------------
# what a pass actually does
# ---------------------------------------------------------------------------
def test_a_watched_file_is_previewed_and_nothing_else(watcher, watch_dir: Path, operational_db: Path):
    _drop(watch_dir)
    before = _counts(operational_db)
    watcher.scan_once()
    result = watcher.scan_once()

    assert len(result.previewed) == 1
    after = _counts(operational_db)
    assert after["punch_events"] == before["punch_events"]      # nothing applied
    assert after["attendance_days"] == before["attendance_days"]
    assert after["import_runs"] == before["import_runs"] + 1

    conn = db.connect(operational_db)
    try:
        row = conn.execute(
            "SELECT status, discovered_by, created_by, preview_json FROM import_runs "
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row["status"] == "previewed"       # stops here, waiting for a human
        assert row["discovered_by"] == "watch"
        assert row["created_by"] == "folder-watch"
        assert row["preview_json"]                # reviewable later
    finally:
        conn.close()


def test_the_operators_file_is_never_moved_or_deleted(watcher, watch_dir: Path):
    path = _drop(watch_dir)
    watcher.scan_once()
    watcher.scan_once()
    assert path.exists(), "the watcher must not consume the program's export"


def test_the_same_file_is_previewed_once(watcher, watch_dir: Path):
    _drop(watch_dir)
    watcher.scan_once()
    assert len(watcher.scan_once().previewed) == 1

    again = watcher.scan_once()
    assert again.previewed == []
    assert again.skipped_already_seen == 1


def test_a_re_export_with_new_content_is_previewed_again(watcher, watch_dir: Path):
    """Same filename every month is normal; content is what identifies a file."""
    _drop(watch_dir)
    watcher.scan_once()
    watcher.scan_once()

    build_export(
        watch_dir / "2026-07.XLS",
        slots=realistic_month() + [SlotSpec("009", "새사람", {3: ["07:20", "16:00"]})],
    )
    watcher.scan_once()
    assert len(watcher.scan_once().previewed) == 1


def test_an_unreadable_file_is_recorded_once_and_left_in_place(watcher, watch_dir: Path, operational_db: Path):
    junk = watch_dir / "broken.xls"
    junk.write_bytes(b"not a workbook")
    _settle(junk)
    watcher.scan_once()
    result = watcher.scan_once()
    assert result.failed == ["broken.xls"]
    assert junk.exists()

    # the failure is recorded, so the next pass does not re-read it forever
    assert watcher.scan_once().failed == []
    conn = db.connect(operational_db)
    try:
        row = conn.execute("SELECT status FROM import_runs ORDER BY id DESC LIMIT 1").fetchone()
        assert row["status"] == "failed"
    finally:
        conn.close()


def test_only_xls_files_are_considered(watcher, watch_dir: Path):
    (watch_dir / "notes.txt").write_text("hello", encoding="utf-8")
    (watch_dir / "book.xlsx").write_bytes(b"PK\x03\x04")
    watcher.scan_once()
    result = watcher.scan_once()
    assert result.previewed == []
    assert result.failed == []


def test_a_missing_folder_is_reported_not_raised(monkeypatch, operational_db: Path, tmp_path: Path):
    monkeypatch.setattr(config, "DB_PATH", operational_db)
    watcher = import_watch.FolderWatcher(tmp_path / "nope", db_path=operational_db)
    assert "does not exist" in watcher.scan_once().reason


def test_a_demo_database_is_refused(monkeypatch, migrated_db: Path, watch_dir: Path, tmp_path: Path):
    seed_demo_database(migrated_db)                 # leaves data_context=demo
    monkeypatch.setattr(config, "DB_PATH", migrated_db)
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "ALLOW_DEMO_IMPORT", False)
    _drop(watch_dir)

    watcher = import_watch.FolderWatcher(watch_dir, db_path=migrated_db)
    watcher.scan_once()
    result = watcher.scan_once()
    assert result.previewed == []
    assert "demo" in result.reason


# ---------------------------------------------------------------------------
# the queue the UI reads
# ---------------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch, operational_db: Path, watch_dir: Path, tmp_path: Path):
    monkeypatch.setattr(config, "DB_PATH", operational_db)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "ALLOW_DEMO_IMPORT", False)
    monkeypatch.setattr(config, "WATCH_DIR", None)   # no thread in tests
    with TestClient(create_app()) as c:
        yield c


def test_pending_lists_what_is_waiting(client, watcher, watch_dir: Path):
    _drop(watch_dir)
    watcher.scan_once()
    run_id = watcher.scan_once().previewed[0]

    body = client.get("/api/v1/imports/pending").json()
    assert [r["importRunId"] for r in body["pending"]] == [run_id]
    assert body["pending"][0]["discoveredBy"] == "watch"
    assert body["pending"][0]["newPunches"] > 0


def test_a_watched_preview_can_be_reopened_and_applied_by_a_person(client, watcher, watch_dir: Path):
    _drop(watch_dir)
    watcher.scan_once()
    run_id = watcher.scan_once().previewed[0]

    preview = client.get(f"/api/v1/imports/{run_id}/preview").json()
    assert preview["importRunId"] == run_id
    assert preview["confirmationToken"]
    assert preview["canApply"] is True

    applied = client.post(
        f"/api/v1/imports/{run_id}/apply",
        json={"confirmationToken": preview["confirmationToken"]},
    )
    assert applied.status_code == 200
    assert applied.json()["inserted"] == preview["newPunches"]
    assert client.get("/api/v1/imports/pending").json()["pending"] == []


def test_a_run_with_no_stored_preview_says_so(client, watcher, watch_dir: Path):
    junk = watch_dir / "broken.xls"
    junk.write_bytes(b"not a workbook")
    _settle(junk)
    watcher.scan_once()
    watcher.scan_once()

    run_id = client.get("/api/v1/imports").json()[0]["id"]
    assert client.get(f"/api/v1/imports/{run_id}/preview").status_code == 409


def test_the_watcher_is_off_unless_a_folder_is_configured(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config, "WATCH_DIR", None)
    assert import_watch.build_from_config() is None

    monkeypatch.setattr(config, "WATCH_DIR", tmp_path)
    monkeypatch.setattr(config, "WATCH_INTERVAL_SECONDS", 900)
    built = import_watch.build_from_config()
    assert built is not None and built.interval_seconds == 900
