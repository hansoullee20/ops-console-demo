"""The read API, and the rule that a network failure never decides which data
the operator sees.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import create_app
from app.seed import canonical
from app.seed.demo_dataset import seed_demo_database


@pytest.fixture
def client(monkeypatch, migrated_db: Path, tmp_path: Path):
    seed_demo_database(migrated_db)
    monkeypatch.setattr(config, "DB_PATH", migrated_db)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    with TestClient(create_app()) as c:
        yield c


def test_bootstrap_matches_the_snapshot_shape(client):
    """One payload shape for both modes, so the frontend has one render path."""
    body = client.get("/api/v1/bootstrap").json()

    assert body["mode"] == "operational"
    assert body["dataContext"] == "demo"          # this database was demo-seeded
    assert body["weekStart"] == canonical.DEMO_WEEK_START
    assert body["today"] == canonical.DEMO_TODAY
    assert len(body["employees"]) == 18
    assert len(body["days"]) == 7
    assert body["fingerprint"]["isStale"] is True

    first = body["employees"][0]
    assert first["name"] == canonical.DEMO_EMPLOYEES[0]["name"]
    assert len(first["cells"]) == 7
    assert first["cells"][1]["issue"] is True


def test_bootstrap_agrees_with_the_generated_snapshot(client, tmp_path: Path):
    """Operational and demo renderings of the same seed must not diverge."""
    import json

    from app.exporters import demo_snapshot

    api = client.get("/api/v1/bootstrap").json()
    text = demo_snapshot.generate(tmp_path / "demo-data.js").read_text(encoding="utf-8")
    snapshot = json.loads(text[text.index("{"): text.rindex("}") + 1])

    assert api["days"] == snapshot["days"]
    assert api["monthStats"] == snapshot["monthStats"]
    assert len(api["employees"]) == len(snapshot["employees"])
    for from_api, from_snapshot in zip(api["employees"], snapshot["employees"]):
        assert from_api["name"] == from_snapshot["name"]
        assert from_api["state"] == from_snapshot["state"]
        for api_cell, snap_cell in zip(from_api["cells"], from_snapshot["cells"]):
            for key, value in snap_cell.items():
                assert api_cell[key] == value


def test_views_are_consistent_across_daily_weekly_monthly(client):
    body = client.get("/api/v1/bootstrap").json()
    stats = body["monthStats"]

    for index, day in enumerate(body["days"]):
        expected: dict[str, int] = {}
        for person in body["employees"]:
            cell = person["cells"][index]
            if cell.get("issue"):
                expected["issue"] = expected.get("issue", 0) + 1
            elif cell["type"] == "leave":
                expected["leave"] = expected.get("leave", 0) + 1
            elif cell["type"] == "sick":
                expected["sick"] = expected.get("sick", 0) + 1
            if cell["type"] == "replacement":
                expected["replace"] = expected.get("replace", 0) + 1
        assert stats.get(str(day["num"]), {}) == expected, f"day {day['num']}"


def test_employee_list_and_profile(client):
    people = client.get("/api/v1/employees").json()
    assert len(people) == 18
    assert people[0]["code"] == "E001"

    profile = client.get("/api/v1/employees/E001").json()
    assert profile["profile"]["name"] == canonical.DEMO_EMPLOYEES[0]["name"]
    assert len(profile["profile"]["cells"]) == 7
    assert client.get("/api/v1/employees/NOPE").status_code == 404


def test_attendance_detail_exposes_raw_punches(client):
    detail = client.get(
        "/api/v1/attendance", params={"employee": "E004", "date": canonical.DEMO_TODAY}
    ).json()
    assert detail["employee"] == "최라온"
    assert detail["reviewFlag"] == "repeated_punch"
    # every raw punch is preserved and visible, not collapsed
    assert len(detail["punches"]) == 3
    assert any(p["review_flag"] == "repeated_punch_candidate" for p in detail["punches"])

    missing = client.get(
        "/api/v1/attendance", params={"employee": "E001", "date": "2030-01-01"}
    )
    assert missing.status_code == 404


def test_leave_surfaces_the_certificate_finding_without_changing_dates(client):
    cases = client.get("/api/v1/leave").json()
    sick = [c for c in cases if c["leaveType"] == "sick"]
    assert sick, "expected the seeded sick-leave case"
    case = sick[0]
    assert case["finding"] is not None
    # neither period is silently adjusted (§7 Phase 4)
    assert case["endDate"] == "2026-09-11"
    assert case["certEndDate"] == "2026-08-31"


def test_replacements_notes_and_documents(client):
    replacements = client.get("/api/v1/replacements").json()
    assert any(r["status"] == "vacancy" and r["substitute"] is None for r in replacements)
    assert any(r["status"] == "assigned" and r["substitute"] for r in replacements)

    assert client.get("/api/v1/notes").json()
    documents = client.get("/api/v1/documents").json()
    assert documents and documents[0]["docType"] == "medical_certificate"


def test_api_never_reports_demo_mode(client):
    """`mode` is how the frontend refuses to render demo data as operational."""
    assert client.get("/api/v1/bootstrap").json()["mode"] == "operational"


MUTATION_ALLOWLIST = {
    ("post", "/api/v1/imports"),
    ("post", "/api/v1/imports/{run_id}/apply"),
    ("post", "/api/v1/imports/{run_id}/rollback"),
    ("post", "/api/v1/imports/{run_id}/refresh"),
    ("post", "/api/v1/terminal-slots"),
    ("post", "/api/v1/terminal-slots/batch"),
    ("post", "/api/v1/terminal-slots/{mapping_id}/close"),
    ("post", "/api/v1/terminal-slots/{mapping_id}/cancel"),
    ("post", "/api/v1/terminal-slots/{mapping_id}/correct"),
    ("post", "/api/v1/leave-operations"),
    ("put", "/api/v1/leave-operations/{leave_id}"),
    ("post", "/api/v1/leave-operations/{leave_id}/approve"),
    ("post", "/api/v1/leave-operations/{leave_id}/cancel"),
    ("post", "/api/v1/replacement-operations"),
    ("patch", "/api/v1/replacement-operations/{assignment_id}"),
    ("patch", "/api/v1/replacement-operations/{assignment_id}/checklist"),
    ("post", "/api/v1/replacement-operations/{assignment_id}/status"),
    ("post", "/api/v1/operations/exceptions/{exception_id}/acknowledge"),
    ("post", "/api/v1/operations/exceptions/{exception_id}/resolve"),
    ("post", "/api/v1/operations/exceptions/{exception_id}/waive"),
    ("post", "/api/v1/attendance/manual-adjustments"),
    ("post", "/api/v1/attendance/manual-adjustments/{adjustment_id}/supersede"),
    ("post", "/api/v1/attendance/manual-adjustments/{adjustment_id}/cancel"),
    ("post", "/api/v1/attendance/manual-adjustments/{adjustment_id}/void"),
    ("post", "/api/v1/employees/{employee_id}/schedules"),
    ("post", "/api/v1/employees/{employee_id}/schedules/{schedule_id}/retire"),
    ("post", "/api/v1/employees/{employee_id}/schedule-dates"),
    ("post", "/api/v1/employees/{employee_id}/schedule-dates/{override_id}/cancel"),
}


def test_only_deliberately_allowlisted_operational_routes_can_write(client):
    """Every operational mutation remains explicitly pinned."""
    schema = create_app().openapi()["paths"]
    exposed = {
        (method.lower(), path)
        for path, operations in schema.items()
        for method in operations
        if method.lower() not in {"get", "head", "options"}
    }
    assert exposed == MUTATION_ALLOWLIST


def test_frontend_is_served_by_allowlist_only(client):
    assert client.get("/").status_code == 200
    assert "text/html" in client.get("/").headers["content-type"]
    for asset in ("profile.css", "profile.js", "data-source.js", "safety-ui.js"):
        assert client.get(f"/{asset}").status_code == 200

    # the operational host must not serve the fictional snapshot at all
    assert client.get("/demo-data.js").status_code == 404
    for forbidden in ("requirements.txt", "pytest.ini", "AI_BUILD_PLAN.md", ".gitignore"):
        assert client.get(f"/{forbidden}").status_code == 404


def test_api_reports_unavailable_when_the_database_is_missing(monkeypatch, tmp_path: Path):
    """The frontend shows an error for this; it must never mean demo data."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "absent.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "MIGRATIONS_DIR", tmp_path / "none")

    with TestClient(create_app()) as c:
        assert c.get("/api/v1/bootstrap").status_code == 503
