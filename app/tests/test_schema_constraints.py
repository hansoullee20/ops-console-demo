"""Schema constraints that encode the non-negotiable data rules.

Each test maps to a numbered rule in AI_BUILD_PLAN.md §2 or a constraint in §3.
"""

from __future__ import annotations

import sqlite3

import pytest


# ---------------------------------------------------------------------------
# §2.2 unique attendance row per employee per work date
# ---------------------------------------------------------------------------
def test_attendance_unique_per_employee_and_date(conn, employee):
    conn.execute(
        "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (?, ?, 'normal')",
        (employee, "2026-08-11"),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (?, ?, 'absent')",
            (employee, "2026-08-11"),
        )
    conn.rollback()

    # the same date for another employee is fine
    other = conn.execute(
        "INSERT INTO employees (employee_code, name, hire_date) VALUES ('E002', '동료', '2024-01-01')"
    ).lastrowid
    conn.execute(
        "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (?, ?, 'normal')",
        (other, "2026-08-11"),
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM attendance_days").fetchone()[0] == 2


def test_attendance_correction_is_an_update_not_a_reinsert(conn, employee):
    conn.execute(
        "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (?, ?, 'absent')",
        (employee, "2026-08-11"),
    )
    conn.commit()
    before = conn.execute("SELECT id, revision FROM attendance_days").fetchone()

    conn.execute(
        "UPDATE attendance_days SET status = 'normal' WHERE employee_id = ? AND work_date = ?",
        (employee, "2026-08-11"),
    )
    conn.commit()
    after = conn.execute("SELECT id, status, revision FROM attendance_days").fetchone()

    assert after["id"] == before["id"]
    assert after["status"] == "normal"
    assert after["revision"] == before["revision"] + 1


def test_attendance_status_is_constrained(conn, employee):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (?, ?, 'nonsense')",
            (employee, "2026-08-12"),
        )
    conn.rollback()


# ---------------------------------------------------------------------------
# foreign key behaviour
# ---------------------------------------------------------------------------
def test_attendance_requires_an_existing_employee(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (99999, '2026-08-11', 'normal')"
        )
    conn.rollback()


def test_employee_delete_is_restricted_while_referenced(conn, employee):
    conn.execute(
        "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (?, '2026-08-11', 'normal')",
        (employee,),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM employees WHERE id = ?", (employee,))
    conn.rollback()

    assert conn.execute("SELECT COUNT(*) FROM attendance_days").fetchone()[0] == 1


def test_leave_evidence_document_foreign_key(conn, employee):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO leave_requests
                (employee_id, leave_type, start_date, end_date, leave_year, evidence_document_id)
            VALUES (?, 'sick', '2026-08-04', '2026-08-11', 2026, 4242)
            """,
            (employee,),
        )
    conn.rollback()

    doc_id = conn.execute(
        """
        INSERT INTO documents (employee_id, entity_type, doc_type, original_filename, stored_path)
        VALUES (?, 'leave_request', 'medical_certificate', 'cert.pdf', 'uploads/cert.pdf')
        """,
        (employee,),
    ).lastrowid
    conn.execute(
        """
        INSERT INTO leave_requests
            (employee_id, leave_type, start_date, end_date, leave_year, evidence_document_id,
             cert_start_date, cert_end_date)
        VALUES (?, 'sick', '2026-08-04', '2026-09-11', 2026, ?, '2026-08-04', '2026-08-31')
        """,
        (employee, doc_id),
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0] == 1


def test_no_foreign_key_violations_in_schema(conn):
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


# ---------------------------------------------------------------------------
# §2.3 / §2.4 raw punch events are immutable source records
# ---------------------------------------------------------------------------
@pytest.fixture
def punch(conn, employee):
    return conn.execute(
        """
        INSERT INTO punch_events
            (terminal_slot_code, punch_at, work_date, punch_type, raw_payload,
             source_filename, source_row_no, employee_id)
        VALUES ('001', '2026-08-11T07:55:00', '2026-08-11', '출', 'raw-row',
                '2026-08.XLS', 12, ?)
        """,
        (employee,),
    ).lastrowid


def test_punch_events_cannot_be_deleted(conn, punch):
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="never be deleted"):
        conn.execute("DELETE FROM punch_events WHERE id = ?", (punch,))
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == 1


def test_punch_events_cannot_be_bulk_deleted(conn, punch):
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="never be deleted"):
        conn.execute("DELETE FROM punch_events")
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == 1


@pytest.mark.parametrize(
    "column, value",
    [
        ("terminal_slot_code", "999"),
        ("punch_at", "2026-08-11T09:00:00"),
        ("work_date", "2026-08-12"),
        ("punch_type", "퇴"),
        ("raw_payload", "tampered"),
        ("source_filename", "other.XLS"),
        ("source_row_no", 99),
        ("source_hash", "deadbeef"),
        ("dedupe_key", "forced"),
        ("created_at", "1999-01-01T00:00:00Z"),
    ],
)
def test_punch_event_raw_columns_are_immutable(conn, punch, column, value):
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(f"UPDATE punch_events SET {column} = ? WHERE id = ?", (value, punch))
    conn.rollback()

    original = conn.execute(
        f"SELECT {column} AS v FROM punch_events WHERE id = ?", (punch,)
    ).fetchone()
    assert original["v"] != value


def test_punch_event_review_columns_stay_editable(conn, punch, employee):
    """Repeated-punch detection is a review flag only (§2.5): it annotates, it
    never rewrites or removes the raw event."""
    conn.execute(
        """
        UPDATE punch_events
           SET review_flag = 'repeated_punch_candidate',
               review_note = '20분 이내 재태그 후보',
               employee_id = ?,
               rolled_back_at = '2026-08-11T10:00:00Z',
               rolled_back_reason = 'import rolled back'
         WHERE id = ?
        """,
        (employee, punch),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM punch_events WHERE id = ?", (punch,)).fetchone()
    assert row["review_flag"] == "repeated_punch_candidate"
    assert row["rolled_back_reason"] == "import rolled back"
    # raw source survived untouched
    assert row["punch_at"] == "2026-08-11T07:55:00"
    assert row["raw_payload"] == "raw-row"


def test_multiple_punches_per_day_are_allowed(conn, employee):
    """3 or 4 punches can be legitimate (출 / 외 / 퇴 / 복) — §2.6."""
    for i, ptype in enumerate(["출", "외", "복", "퇴"]):
        conn.execute(
            """
            INSERT INTO punch_events (terminal_slot_code, punch_at, work_date, punch_type, employee_id)
            VALUES ('001', ?, '2026-08-11', ?, ?)
            """,
            (f"2026-08-11T0{7 + i}:55:00", ptype, employee),
        )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == 4


def test_close_in_time_punches_are_storable(conn, employee):
    """Near-identical punches must be storable and flagged, never rejected or
    deleted as duplicates (§2.4, §2.5)."""
    for stamp in ("2026-08-11T07:55:00", "2026-08-11T08:01:00"):
        conn.execute(
            """
            INSERT INTO punch_events (terminal_slot_code, punch_at, work_date, punch_type,
                                      employee_id, review_flag)
            VALUES ('001', ?, '2026-08-11', '출', ?, 'repeated_punch_candidate')
            """,
            (stamp, employee),
        )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == 2


def test_reimport_dedupe_key_is_unique_but_optional(conn, employee):
    conn.execute(
        """
        INSERT INTO punch_events (terminal_slot_code, punch_at, work_date, punch_type, dedupe_key)
        VALUES ('001', '2026-08-11T07:55:00', '2026-08-11', '출', 'k1')
        """
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO punch_events (terminal_slot_code, punch_at, work_date, punch_type, dedupe_key)
            VALUES ('001', '2026-08-11T07:55:00', '2026-08-11', '출', 'k1')
            """
        )
    conn.rollback()

    # NULL dedupe keys do not collide — raw events without one are still storable
    for _ in range(2):
        conn.execute(
            """
            INSERT INTO punch_events (terminal_slot_code, punch_at, work_date, punch_type)
            VALUES ('002', '2026-08-11T07:56:00', '2026-08-11', '출')
            """
        )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == 3


def test_punch_event_can_exist_without_employee_mapping(conn):
    """Terminal slot != roster: an unmapped slot's punches are still preserved (§3)."""
    conn.execute(
        """
        INSERT INTO punch_events (terminal_slot_code, punch_at, work_date, punch_type, review_flag)
        VALUES ('077', '2026-08-11T07:55:00', '2026-08-11', '출', 'unmapped_slot')
        """
    )
    conn.commit()
    row = conn.execute("SELECT employee_id, review_flag FROM punch_events").fetchone()
    assert row["employee_id"] is None
    assert row["review_flag"] == "unmapped_slot"


def test_terminal_slot_mapping_exists(conn, employee):
    conn.execute(
        """
        INSERT INTO terminal_slots (slot_code, employee_id, effective_from, status)
        VALUES ('001', ?, '2024-01-01', 'mapped')
        """,
        (employee,),
    )
    conn.execute(
        "INSERT INTO terminal_slots (slot_code, effective_from, status) VALUES ('077', '2024-01-01', 'unmapped')"
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM terminal_slots").fetchone()[0] == 2

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO terminal_slots (slot_code, effective_from) VALUES ('001', '2024-01-01')"
        )
    conn.rollback()


# ---------------------------------------------------------------------------
# §2.7 substitute assignment never overwrites normal attendance
# ---------------------------------------------------------------------------
def test_replacement_does_not_touch_attendance(conn, employee):
    substitute = conn.execute(
        "INSERT INTO employees (employee_code, name, hire_date, employment_type) "
        "VALUES ('E003', '대체', '2025-04-01', 'substitute')"
    ).lastrowid
    conn.execute(
        "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (?, '2026-08-11', 'leave')",
        (employee,),
    )
    conn.execute(
        "INSERT INTO attendance_days (employee_id, work_date, status) VALUES (?, '2026-08-11', 'normal')",
        (substitute,),
    )
    conn.commit()

    conn.execute(
        """
        INSERT INTO replacement_assignments
            (work_date, zone, absent_employee_id, substitute_employee_id, status)
        VALUES ('2026-08-11', '본관 4층', ?, ?, 'assigned')
        """,
        (employee, substitute),
    )
    conn.commit()

    rows = {
        r["employee_id"]: (r["status"], r["revision"])
        for r in conn.execute("SELECT employee_id, status, revision FROM attendance_days")
    }
    assert rows[employee] == ("leave", 1)
    assert rows[substitute] == ("normal", 1)


def test_substitute_cannot_be_double_booked(conn, employee):
    substitute = conn.execute(
        "INSERT INTO employees (employee_code, name, hire_date) VALUES ('E004', '대체2', '2025-04-01')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO replacement_assignments (work_date, shift, absent_employee_id, substitute_employee_id, status)
        VALUES ('2026-08-11', 'day', ?, ?, 'assigned')
        """,
        (employee, substitute),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO replacement_assignments (work_date, shift, substitute_employee_id, status)
            VALUES ('2026-08-11', 'day', ?, 'assigned')
            """,
            (substitute,),
        )
    conn.rollback()

    # a cancelled assignment does not block a new one
    conn.execute(
        """
        INSERT INTO replacement_assignments (work_date, shift, substitute_employee_id, status)
        VALUES ('2026-08-11', 'night', ?, 'cancelled')
        """,
        (substitute,),
    )
    conn.commit()


def test_employee_cannot_replace_themselves(conn, employee):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO replacement_assignments
                (work_date, absent_employee_id, substitute_employee_id, status)
            VALUES ('2026-08-11', ?, ?, 'assigned')
            """,
            (employee, employee),
        )
    conn.rollback()


# ---------------------------------------------------------------------------
# §2.9 / §2.16 leave modelling
# ---------------------------------------------------------------------------
def test_leave_balance_is_year_specific(conn, employee):
    for year, granted in ((2025, 15.0), (2026, 16.0)):
        conn.execute(
            "INSERT INTO leave_balances (employee_id, leave_year, granted_days) VALUES (?, ?, ?)",
            (employee, year, granted),
        )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO leave_balances (employee_id, leave_year, granted_days) VALUES (?, 2026, 1)",
            (employee,),
        )
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM leave_balances").fetchone()[0] == 2


def test_half_day_leave_requires_a_period(conn, employee):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, leave_year)
            VALUES (?, 'half_day', '2026-08-11', '2026-08-11', 2026)
            """,
            (employee,),
        )
    conn.rollback()

    conn.execute(
        """
        INSERT INTO leave_requests
            (employee_id, leave_type, half_day_period, start_date, end_date, leave_year, working_day_count)
        VALUES (?, 'half_day', 'am', '2026-08-11', '2026-08-11', 2026, 0.5)
        """,
        (employee,),
    )
    conn.commit()
    assert conn.execute("SELECT working_day_count FROM leave_requests").fetchone()[0] == 0.5


def test_leave_dates_must_be_ordered(conn, employee):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, leave_year)
            VALUES (?, 'annual', '2026-08-11', '2026-08-01', 2026)
            """,
            (employee,),
        )
    conn.rollback()


def test_overlapping_leave_is_storable_for_detection(conn, employee):
    """Overlaps must be detectable, not silently blocked at insert time (§2.13):
    the deterministic rule layer decides what to do with them."""
    for start, end in (("2026-08-04", "2026-08-11"), ("2026-08-10", "2026-08-14")):
        conn.execute(
            """
            INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, leave_year, status)
            VALUES (?, 'annual', ?, ?, 2026, 'requested')
            """,
            (employee, start, end),
        )
    conn.commit()

    overlaps = conn.execute(
        """
        SELECT a.id, b.id FROM leave_requests a JOIN leave_requests b
          ON a.employee_id = b.employee_id AND a.id < b.id
         AND a.start_date <= b.end_date AND b.start_date <= a.end_date
        """
    ).fetchall()
    assert len(overlaps) == 1


# ---------------------------------------------------------------------------
# §2.17 site calendar, §2.12 audit log
# ---------------------------------------------------------------------------
def test_site_calendar_marks_non_working_days(conn):
    conn.executemany(
        "INSERT INTO site_calendar (calendar_date, day_type, is_working, label) VALUES (?, ?, ?, ?)",
        [
            ("2026-08-11", "working", 1, None),
            ("2026-08-15", "holiday", 0, "광복절"),
            ("2026-08-16", "weekend", 0, None),
        ],
    )
    conn.commit()
    working = conn.execute(
        "SELECT COUNT(*) FROM site_calendar WHERE is_working = 1 "
        "AND calendar_date BETWEEN '2026-08-11' AND '2026-08-16'"
    ).fetchone()[0]
    assert working == 1


def test_audit_log_is_append_only(conn, employee):
    conn.execute(
        """
        INSERT INTO audit_log (actor_type, actor_id, action, entity_type, entity_id,
                               before_json, after_json, reason)
        VALUES ('user', 'admin', 'attendance.update', 'attendance_days', 1,
                '{"status":"absent"}', '{"status":"normal"}', '수기 정정')
        """
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_log SET reason = 'tampered' WHERE id = 1")
    conn.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_log WHERE id = 1")
    conn.rollback()

    assert conn.execute("SELECT reason FROM audit_log").fetchone()[0] == "수기 정정"


def test_import_run_lifecycle_states(conn):
    run_id = conn.execute(
        "INSERT INTO import_runs (source_filename, status) VALUES ('2026-08.XLS', 'pending')"
    ).lastrowid
    for state in ("previewed", "applied", "rolled_back"):
        conn.execute("UPDATE import_runs SET status = ? WHERE id = ?", (state, run_id))
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE import_runs SET status = 'whatever' WHERE id = ?", (run_id,))
    conn.rollback()
    assert conn.execute("SELECT status FROM import_runs").fetchone()[0] == "rolled_back"


def test_import_run_cannot_be_deleted_while_punches_reference_it(conn, employee):
    run_id = conn.execute(
        "INSERT INTO import_runs (source_filename, status) VALUES ('2026-08.XLS', 'applied')"
    ).lastrowid
    conn.execute(
        """
        INSERT INTO punch_events (terminal_slot_code, punch_at, work_date, punch_type,
                                  employee_id, import_run_id)
        VALUES ('001', '2026-08-11T07:55:00', '2026-08-11', '출', ?, ?)
        """,
        (employee, run_id),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM import_runs WHERE id = ?", (run_id,))
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == 1


def test_timestamps_are_populated_and_maintained(conn, employee):
    row = conn.execute("SELECT created_at, updated_at FROM employees WHERE id = ?", (employee,)).fetchone()
    assert row["created_at"] and row["updated_at"]

    conn.execute("UPDATE employees SET zone = '본관 2층' WHERE id = ?", (employee,))
    conn.commit()
    after = conn.execute("SELECT created_at, updated_at FROM employees WHERE id = ?", (employee,)).fetchone()
    assert after["created_at"] == row["created_at"]
    assert after["updated_at"] >= row["updated_at"]
