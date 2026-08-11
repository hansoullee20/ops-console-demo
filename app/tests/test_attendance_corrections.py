"""Finding N1: attendance corrections must never destroy and recreate the row.

Nothing in the schema enforces this — a `BEFORE INSERT` guard would also block
the legitimate `ON CONFLICT DO UPDATE` upsert that Phase 3 needs, and a
no-DELETE trigger would block import rollback. So the guarantee lives in
`app/services/attendance.py` and is pinned here.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from app import db
from app.config import REPO_ROOT
from app.services.attendance import (
    AttendanceCorrectionError,
    correct_attendance,
)


@pytest.fixture
def attendance_day(conn, employee):
    conn.execute(
        """
        INSERT INTO attendance_days (employee_id, work_date, status, review_note)
        VALUES (?, '2026-08-11', 'absent', '수기 확인 필요')
        """,
        (employee,),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM attendance_days").fetchone())


def _row(conn):
    return dict(conn.execute("SELECT * FROM attendance_days").fetchone())


# ---------------------------------------------------------------------------
# the four required guarantees
# ---------------------------------------------------------------------------
def test_correction_preserves_identity_and_history(conn, employee, attendance_day):
    result = correct_attendance(
        conn,
        employee_id=employee,
        work_date="2026-08-11",
        changes={"status": "normal"},
        actor_id="admin",
        reason="지문 재확인 후 정정",
    )
    conn.commit()
    after = _row(conn)

    assert after["id"] == attendance_day["id"]
    assert after["created_at"] == attendance_day["created_at"]
    assert after["revision"] == attendance_day["revision"] + 1
    assert after["status"] == "normal"
    # untouched fields survive — this is what INSERT OR REPLACE destroys
    assert after["review_note"] == "수기 확인 필요"

    assert result.attendance_id == attendance_day["id"]
    assert result.revision_after == result.revision_before + 1


def test_correction_writes_audit_in_the_same_transaction(conn, employee, attendance_day):
    result = correct_attendance(
        conn,
        employee_id=employee,
        work_date="2026-08-11",
        changes={"status": "normal"},
        actor_id="admin",
        reason="지문 재확인 후 정정",
        provider="local",
        session_ref="sess-1",
    )

    # visible before the commit: same transaction, not a follow-up write
    audit = dict(conn.execute("SELECT * FROM audit_log WHERE id = ?", (result.audit_id,)).fetchone())
    assert audit["action"] == "attendance.correct"
    assert audit["entity_type"] == "attendance_days"
    assert audit["entity_id"] == attendance_day["id"]
    assert audit["reason"] == "지문 재확인 후 정정"
    assert audit["actor_id"] == "admin"
    assert audit["provider"] == "local"
    assert json.loads(audit["before_json"]) == {"status": "absent"}
    assert json.loads(audit["after_json"]) == {"status": "normal"}

    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 1


def test_rollback_cancels_both_the_change_and_the_audit(conn, employee, attendance_day):
    correct_attendance(
        conn,
        employee_id=employee,
        work_date="2026-08-11",
        changes={"status": "normal", "review_note": "정정됨"},
        actor_id="admin",
        reason="정정",
    )
    conn.rollback()

    after = _row(conn)
    assert after["status"] == "absent"
    assert after["review_note"] == "수기 확인 필요"
    assert after["revision"] == attendance_day["revision"]
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_revision_increments_once_per_correction_not_per_field(conn, employee, attendance_day):
    correct_attendance(
        conn,
        employee_id=employee,
        work_date="2026-08-11",
        changes={"status": "normal", "actual_in_at": "07:55", "actual_out_at": "16:02"},
        actor_id="admin",
        reason="3개 필드 동시 정정",
    )
    conn.commit()
    assert _row(conn)["revision"] == attendance_day["revision"] + 1


def test_repeated_corrections_accumulate_revisions_and_audit_rows(conn, employee, attendance_day):
    for index, status in enumerate(("normal", "late", "early_leave"), start=1):
        correct_attendance(
            conn,
            employee_id=employee,
            work_date="2026-08-11",
            changes={"status": status},
            actor_id="admin",
            reason=f"정정 {index}",
        )
        conn.commit()
        assert _row(conn)["revision"] == attendance_day["revision"] + index
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == index

    assert _row(conn)["id"] == attendance_day["id"]
    assert _row(conn)["created_at"] == attendance_day["created_at"]


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("field", ["id", "employee_id", "work_date", "created_at", "revision"])
def test_protected_fields_cannot_be_corrected(conn, employee, attendance_day, field):
    with pytest.raises(AttendanceCorrectionError, match="protected field"):
        correct_attendance(
            conn,
            employee_id=employee,
            work_date="2026-08-11",
            changes={field: 999},
            actor_id="admin",
            reason="시도",
        )
    assert _row(conn) == attendance_day


def test_unknown_field_is_refused(conn, employee, attendance_day):
    with pytest.raises(AttendanceCorrectionError, match="unknown attendance field"):
        correct_attendance(
            conn, employee_id=employee, work_date="2026-08-11",
            changes={"nonsense": 1}, actor_id="admin", reason="시도",
        )


def test_correction_requires_a_reason(conn, employee, attendance_day):
    for reason in ("", "   "):
        with pytest.raises(AttendanceCorrectionError, match="reason"):
            correct_attendance(
                conn, employee_id=employee, work_date="2026-08-11",
                changes={"status": "normal"}, actor_id="admin", reason=reason,
            )
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_empty_change_set_is_refused(conn, employee, attendance_day):
    with pytest.raises(AttendanceCorrectionError, match="at least one field"):
        correct_attendance(
            conn, employee_id=employee, work_date="2026-08-11",
            changes={}, actor_id="admin", reason="빈 변경",
        )


def test_correcting_a_missing_day_is_refused_not_created(conn, employee):
    """Creating the row here is exactly what tempts callers into
    INSERT OR REPLACE."""
    with pytest.raises(AttendanceCorrectionError, match="never create"):
        correct_attendance(
            conn, employee_id=employee, work_date="2026-12-25",
            changes={"status": "normal"}, actor_id="admin", reason="없는 날",
        )
    assert conn.execute("SELECT COUNT(*) FROM attendance_days").fetchone()[0] == 0


def test_invalid_status_is_rejected_by_the_schema(conn, employee, attendance_day):
    with pytest.raises(sqlite3.IntegrityError):
        correct_attendance(
            conn, employee_id=employee, work_date="2026-08-11",
            changes={"status": "nonsense"}, actor_id="admin", reason="잘못된 상태",
        )
    conn.rollback()
    assert _row(conn)["status"] == "absent"


# ---------------------------------------------------------------------------
# the destructive idioms must not appear anywhere in the codebase
# ---------------------------------------------------------------------------
DESTRUCTIVE = re.compile(
    r"\b(INSERT\s+OR\s+REPLACE|REPLACE\s+INTO|UPDATE\s+OR\s+REPLACE)\b", re.IGNORECASE
)
GUARDED_TABLES = ("attendance_days", "leave_balances", "terminal_slots")


def _executed_sql(path: Path) -> list[str]:
    """Every SQL string actually handed to execute()/executescript().

    Scanning the whole file would trip over prose: this module's own docstrings
    describe the forbidden idiom in order to explain why it is forbidden.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    source = path.read_text(encoding="utf-8")
    statements: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"execute", "executemany", "executescript"}:
            continue
        if not node.args:
            continue
        segment = ast.get_source_segment(source, node.args[0])
        if segment:
            statements.append(segment)
    return statements


def test_no_destructive_replace_idiom_in_application_code():
    """Finding N1 has no schema guard, so the rule is held here."""
    offenders = []

    for path in (REPO_ROOT / "app").rglob("*.py"):
        if "tests" in path.parts:
            continue
        for statement in _executed_sql(path):
            match = DESTRUCTIVE.search(statement)
            if match and any(table in statement for table in GUARDED_TABLES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")

    for path in (REPO_ROOT / "app" / "migrations").glob("*.sql"):
        code = "\n".join(
            line.split("--", 1)[0]
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        for match in DESTRUCTIVE.finditer(code):
            window = code[match.start(): match.start() + 400]
            if any(table in window for table in GUARDED_TABLES):
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)}")

    assert offenders == [], (
        "destructive replace idiom used on a guarded table (finding N1): "
        + "; ".join(offenders)
    )


def test_the_guard_detects_a_real_violation(tmp_path: Path):
    """The guard above only means something if it can fail."""
    offender = tmp_path / "bad.py"
    offender.write_text(
        "def go(conn):\n"
        "    conn.execute(\"INSERT OR REPLACE INTO attendance_days (id) VALUES (1)\")\n",
        encoding="utf-8",
    )
    statements = _executed_sql(offender)
    assert any(
        DESTRUCTIVE.search(s) and "attendance_days" in s for s in statements
    ), "the detector would not have caught a genuine violation"


def test_the_destructive_idiom_really_is_destructive(conn, employee, attendance_day):
    """Documents *why* the rule exists, so nobody relaxes it later.

    This is the behaviour the service exists to avoid; it is asserted here
    rather than used anywhere in the application.
    """
    conn.execute(
        "INSERT OR REPLACE INTO attendance_days (employee_id, work_date, status) "
        "VALUES (?, '2026-08-11', 'normal')",
        (employee,),
    )
    conn.commit()
    after = _row(conn)

    assert after["id"] != attendance_day["id"]          # row destroyed and recreated
    assert after["revision"] == 1                        # correction history lost
    assert after["review_note"] is None                  # note silently dropped
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0  # no trace
