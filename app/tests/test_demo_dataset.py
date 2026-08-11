"""The demo dataset must live in exactly one place.

The public snapshot is generated from a seeded database, so these tests prove
the database really is the source of truth: seed it, read it back through the
same read models the API uses, and require the result to equal the canonical
fixture cell for cell.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import db, migrate
from app.exporters import demo_snapshot
from app.seed import canonical
from app.seed.demo_dataset import seed_demo_database
from app.services import ops, presentation


@pytest.fixture
def seeded(migrated_db: Path) -> Path:
    seed_demo_database(migrated_db)
    return migrated_db


def test_seed_marks_the_database_as_demo(seeded: Path):
    """A demo-seeded file must never be mistaken for a real one — recorded once
    at database level, not as a flag on every business row."""
    with db.connection(seeded) as conn:
        meta = ops.data_context(conn)
        assert meta["data_context"] == "demo"
        assert meta["demo_week_start"] == canonical.DEMO_WEEK_START
        assert meta["demo_today"] == canonical.DEMO_TODAY

        for table in ("employees", "attendance_days", "punch_events", "leave_requests"):
            columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert "is_demo" not in columns, f"{table} grew a per-row demo flag"


def test_seed_refuses_to_touch_a_populated_database(seeded: Path):
    with db.transaction(seeded) as conn:
        before = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]

    summary = seed_demo_database(seeded)
    assert summary.skipped is True

    with db.connection(seeded) as conn:
        assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before


def test_seed_populates_every_view_table(seeded: Path):
    with db.connection(seeded) as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "employees", "terminal_slots", "leave_balances", "site_calendar",
                "attendance_days", "punch_events", "leave_requests",
                "replacement_assignments", "notes", "documents",
            )
        }
    assert counts["employees"] == len(canonical.DEMO_EMPLOYEES) == 18
    for table, count in counts.items():
        assert count > 0, f"{table} was left empty by the seed"


def test_week_view_round_trips_the_canonical_fixture(seeded: Path):
    """The strongest guarantee that there is no second dataset: what comes back
    out of the database equals what went in, field by field and cell by cell."""
    with db.connection(seeded) as conn:
        view = ops.week_view(conn, canonical.DEMO_WEEK_START, canonical.DEMO_TODAY)

    assert view["days"] == canonical.DEMO_DAYS
    assert len(view["employees"]) == len(canonical.DEMO_EMPLOYEES)

    for got, expected in zip(view["employees"], canonical.DEMO_EMPLOYEES):
        for field in ("name", "zone", "hire", "end", "leave", "slot", "state"):
            assert got[field] == expected[field], f"{expected['name']}.{field}"
        assert got["cells"] == expected["cells"], f"{expected['name']} cells"


def test_issue_cells_are_stored_as_situations_not_labels(seeded: Path):
    """The four demo findings are stored as the facts that cause them, so the
    labels are derived rather than hard-coded into the database."""
    with db.connection(seeded) as conn:
        flags = dict(
            conn.execute(
                """
                SELECT e.name, a.review_flag FROM attendance_days a
                  JOIN employees e ON e.id = a.employee_id
                 WHERE a.work_date = ? AND a.review_flag IS NOT NULL
                """,
                (canonical.DEMO_TODAY,),
            ).fetchall()
        )
        assert flags == {
            "김가람": "cert_period_mismatch",
            "박나래": "vacancy_unstaffed",
            "이도연": "leave_punch_conflict",
            "최라온": "repeated_punch",
        }

        # a vacancy is never recorded as confirmed absence (§3, §2.14)
        status = conn.execute(
            "SELECT a.status FROM attendance_days a JOIN employees e ON e.id = a.employee_id "
            "WHERE e.name = '박나래' AND a.work_date = ?",
            (canonical.DEMO_TODAY,),
        ).fetchone()[0]
        assert status == "unknown"

        # the certificate really is shorter than the sick leave
        leave = conn.execute(
            "SELECT l.start_date, l.end_date, l.cert_start_date, l.cert_end_date "
            "FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
            "WHERE e.name = '김가람' AND l.leave_type = 'sick'"
        ).fetchone()
        assert leave["cert_end_date"] < leave["end_date"]

        # the repeated-punch day keeps all three raw events, flagged not removed
        punches = conn.execute(
            "SELECT p.punch_at, p.review_flag FROM punch_events p "
            "JOIN employees e ON e.id = p.employee_id "
            "WHERE e.name = '최라온' AND p.work_date = ? ORDER BY p.punch_at",
            (canonical.DEMO_TODAY,),
        ).fetchall()
        assert len(punches) == 3
        assert any(row["review_flag"] == "repeated_punch_candidate" for row in punches)


def test_month_stats_agree_with_the_week_view(seeded: Path):
    """The monthly aggregate is derived from the same rows the weekly grid
    renders, so the two cannot disagree. The previous hand-written mock did:
    it showed a leave on 8/12–8/14 while omitting a concurrent sick leave."""
    with db.connection(seeded) as conn:
        stats = ops.month_stats(conn, canonical.DEMO_YEAR, canonical.DEMO_MONTH)
        view = ops.week_view(conn, canonical.DEMO_WEEK_START, canonical.DEMO_TODAY)

    for index, iso in enumerate(view["dates"]):
        day = str(int(iso[8:10]))
        expected: dict[str, int] = {}
        for person in view["employees"]:
            cell = person["cells"][index]
            if cell.get("issue"):
                expected["issue"] = expected.get("issue", 0) + 1
            elif cell["type"] == "leave":
                expected["leave"] = expected.get("leave", 0) + 1
            elif cell["type"] == "sick":
                expected["sick"] = expected.get("sick", 0) + 1
            if cell["type"] == "replacement":
                expected["replace"] = expected.get("replace", 0) + 1
        assert stats.get(day, {}) == expected, f"{iso} disagrees with the weekly grid"

    # 8/12-8/14 now report the sick leave the old mock dropped
    for day in ("12", "13", "14"):
        assert stats[day] == {"sick": 1, "leave": 1}


def test_snapshot_is_generated_and_self_describing(tmp_path: Path):
    target = demo_snapshot.generate(tmp_path / "demo-data.js")
    text = target.read_text(encoding="utf-8")

    assert text.startswith("// GENERATED FILE")
    assert "do not commit" in text
    assert text.lstrip().startswith("//")

    payload = json.loads(text[text.index("{"): text.rindex("}") + 1])
    assert payload["mode"] == "demo"
    assert payload["today"] == canonical.DEMO_TODAY
    assert payload["days"] == canonical.DEMO_DAYS
    assert len(payload["employees"]) == 18
    assert payload["employees"][0]["cells"] == canonical.DEMO_EMPLOYEES[0]["cells"]


def test_snapshot_is_deterministic(tmp_path: Path):
    """The demo must render identically forever and must not drift with the
    real calendar."""
    first = demo_snapshot.generate(tmp_path / "a.js").read_text(encoding="utf-8")
    second = demo_snapshot.generate(tmp_path / "b.js").read_text(encoding="utf-8")
    assert first == second
    assert canonical.DEMO_TODAY in first


def test_snapshot_is_not_committed_to_the_repository():
    from app.config import REPO_ROOT

    assert not (REPO_ROOT / "demo-data.js").exists(), (
        "demo-data.js is generated at deploy time and must not be committed; "
        "committing it recreates the duplicate dataset it exists to avoid"
    )


def test_seed_and_export_need_no_third_party_packages():
    """The Pages deploy runs these without `pip install`, so they must not
    reach for FastAPI or pydantic."""
    import ast

    for module in (
        "app/seed/demo_dataset.py",
        "app/seed/canonical.py",
        "app/exporters/demo_snapshot.py",
        "app/services/ops.py",
        "app/services/presentation.py",
        "app/db.py",
        "app/migrate.py",
        "app/config.py",
    ):
        from app.config import REPO_ROOT

        tree = ast.parse((REPO_ROOT / module).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        forbidden = imported & {"fastapi", "pydantic", "starlette", "uvicorn", "httpx"}
        assert not forbidden, f"{module} imports {forbidden}"


def test_weekday_calculation_matches_the_calendar():
    assert presentation.build_days(["2026-08-10"], None)[0]["dow"] == "월"
    assert presentation.build_days(["2026-08-15"], None)[0]["dow"] == "토"
    assert presentation.build_days(["2026-08-16"], None)[0]["dow"] == "일"
    assert presentation.build_days(["2024-02-29"], None)[0]["dow"] == "목"

    marked = presentation.build_days(["2026-08-11"], "2026-08-11")[0]
    assert marked["today"] is True and marked["dow"] == "화 · 오늘"


def test_punch_formatting_keeps_every_punch_visible():
    assert presentation.format_punches([]) == ""
    assert presentation.format_punches(["07:55"]) == "07:55"
    assert presentation.format_punches(["07:55", "16:02"]) == "07:55 / 16:02"
    # 3+ punches are legitimate (출/외/퇴/복) and must not be collapsed
    assert presentation.format_punches(["07:55", "08:01", "16:04"]) == "07:55 · 08:01 · 16:04"
