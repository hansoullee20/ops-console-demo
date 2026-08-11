"""Normalise the canonical fictional dataset into the Phase 1 schema.

The demo's people and their week are defined once, in `app/seed/canonical.py`.
This module writes them into real tables — employees, attendance_days,
punch_events, leave_requests, replacement_assignments, leave_balances,
terminal_slots, site_calendar, notes, documents — so the API and the public
snapshot both read from a database rather than from a second copy of the data.

Presentation strings (정상 / 연차 / 결원 …) are deliberately NOT stored. The
database keeps facts; `app/services/presentation.py` turns facts back into the
labels the existing UI expects. The four "issue" cells in the demo are stored
as the situations that cause them:

    cert_period_mismatch   sick leave running past the medical certificate
    vacancy_unstaffed      an open vacancy with no substitute assigned
    leave_punch_conflict   approved leave with fingerprint punches on the day
    repeated_punch         three or more punches, some close together

Standard library only: the Pages deploy runs this without `pip install`.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app import config, db
from app.seed.canonical import (
    DEMO_EMPLOYEES,
    DEMO_MONTH,
    DEMO_MONTH_STATS,
    DEMO_TODAY,
    DEMO_WEEK_DATES,
    DEMO_WEEK_START,
    DEMO_YEAR,
)

TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")

# cell type -> attendance_days.status
STATUS_BY_CELL_TYPE = {
    "ok": "normal",
    "leave": "leave",
    "sick": "sick_leave",
    "off": "off",
    "replacement": "normal",
}

# The demo week: 2026-08-15 is a Saturday, 2026-08-16 a Sunday.
NON_WORKING_DATES = {"2026-08-15": ("weekend", "광복절"), "2026-08-16": ("weekend", None)}

SCHEDULED_START = "08:00"
SCHEDULED_END = "17:00"


@dataclass
class SeedSummary:
    counts: dict[str, int] = field(default_factory=dict)
    skipped: bool = False


def _times_in(text: str | None) -> list[str]:
    return TIME_RE.findall(text or "")


def _issue_code(cell: dict) -> str | None:
    """Classify a demo issue cell into the situation that causes it."""
    if not cell.get("issue"):
        return None
    label = cell.get("label", "")
    if label == "병가":
        return "cert_period_mismatch"
    if label == "결원":
        return "vacancy_unstaffed"
    if label.startswith("휴가"):
        return "leave_punch_conflict"
    if label == "다중 태그":
        return "repeated_punch"
    return "other"


def _employee_code(index: int) -> str:
    return f"E{index + 1:03d}"


def database_is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 0


def seed_demo_database(
    db_path: Path | str | None = None, *, force: bool = False
) -> SeedSummary:
    """Write the fictional dataset. Refuses to touch a non-empty database."""
    path = Path(db_path) if db_path is not None else config.DB_PATH
    summary = SeedSummary()

    conn = db.connect(path)
    try:
        if not database_is_empty(conn) and not force:
            summary.skipped = True
            return summary

        with conn:
            _seed(conn, summary)
        return summary
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection, summary: SeedSummary) -> None:
    counts = {k: 0 for k in (
        "employees", "terminal_slots", "leave_balances", "site_calendar",
        "attendance_days", "punch_events", "leave_requests",
        "replacement_assignments", "notes", "documents",
    )}

    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES ('data_context', 'demo') "
        "ON CONFLICT(key) DO UPDATE SET value = 'demo'"
    )
    for key, value in (
        ("demo_week_start", DEMO_WEEK_START),
        ("demo_today", DEMO_TODAY),
    ):
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # --- site calendar -----------------------------------------------------
    for iso in DEMO_WEEK_DATES:
        day_type, label = NON_WORKING_DATES.get(iso, ("working", None))
        conn.execute(
            "INSERT INTO site_calendar (calendar_date, day_type, is_working, label) "
            "VALUES (?, ?, ?, ?)",
            (iso, day_type, 0 if day_type != "working" else 1, label),
        )
        counts["site_calendar"] += 1

    # --- employees, slots, balances ---------------------------------------
    employee_ids: dict[str, int] = {}
    for index, person in enumerate(DEMO_EMPLOYEES):
        cur = conn.execute(
            """
            INSERT INTO employees (employee_code, name, zone, hire_date, end_date,
                                   employment_type, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                _employee_code(index),
                person["name"],
                person["zone"],
                person["hire"],
                person["end"],
                "substitute" if any(c["type"] == "replacement" for c in person["cells"]) else "regular",
            ),
        )
        employee_ids[person["name"]] = int(cur.lastrowid)
        counts["employees"] += 1

        conn.execute(
            """
            INSERT INTO terminal_slots (slot_code, employee_id, effective_from, status)
            VALUES (?, ?, ?, 'mapped')
            """,
            (person["slot"], employee_ids[person["name"]], person["hire"]),
        )
        counts["terminal_slots"] += 1

        conn.execute(
            """
            INSERT INTO leave_balances (employee_id, leave_year, granted_days, used_days)
            VALUES (?, ?, ?, 0)
            """,
            (employee_ids[person["name"]], DEMO_YEAR, float(person["leave"])),
        )
        counts["leave_balances"] += 1

    # --- per-day rows ------------------------------------------------------
    for person in DEMO_EMPLOYEES:
        employee_id = employee_ids[person["name"]]
        for index, cell in enumerate(person["cells"]):
            iso = DEMO_WEEK_DATES[index]
            code = _issue_code(cell)
            status = STATUS_BY_CELL_TYPE.get(cell["type"])
            if status is None:
                # an issue cell whose presentation type is not a real status
                status = "sick_leave" if code == "cert_period_mismatch" else "unknown"
            if code == "leave_punch_conflict":
                status = "leave"
            elif code == "repeated_punch":
                status = "normal"
            elif code == "vacancy_unstaffed":
                # never record an unexplained gap as confirmed absence
                status = "unknown"

            working = status in {"normal"}
            conn.execute(
                """
                INSERT INTO attendance_days
                    (employee_id, work_date, status, scheduled_start, scheduled_end,
                     source, review_flag, review_note)
                VALUES (?, ?, ?, ?, ?, 'derived', ?, ?)
                """,
                (
                    employee_id,
                    iso,
                    status,
                    SCHEDULED_START if status != "off" else None,
                    SCHEDULED_END if status != "off" else None,
                    code,
                    cell.get("detail"),
                ),
            )
            counts["attendance_days"] += 1

            times = _times_in(cell.get("punch"))
            for order, hhmm in enumerate(times):
                is_last = order == len(times) - 1
                conn.execute(
                    """
                    INSERT INTO punch_events
                        (terminal_slot_code, punch_at, work_date, punch_type, raw_payload,
                         source_filename, employee_id, dedupe_key, review_flag)
                    VALUES (?, ?, ?, ?, ?, 'demo-seed', ?, ?, ?)
                    """,
                    (
                        person["slot"],
                        f"{iso}T{hhmm}:00",
                        iso,
                        "퇴" if is_last else "출",
                        f"{person['slot']} {iso} {hhmm}",
                        employee_id,
                        f"{person['slot']}|{iso}|{hhmm}",
                        "repeated_punch_candidate" if code == "repeated_punch" and not is_last else None,
                    ),
                )
                counts["punch_events"] += 1

            if working and not times:
                continue

    # --- leave requests ----------------------------------------------------
    for person in DEMO_EMPLOYEES:
        employee_id = employee_ids[person["name"]]
        runs = _contiguous(person["cells"], {"leave", "sick"})
        for leave_type, first, last, codes in runs:
            code = next((c for c in codes if c), None)
            cert_start = cert_end = None
            start_date, end_date = DEMO_WEEK_DATES[first], DEMO_WEEK_DATES[last]
            if code == "cert_period_mismatch":
                # the situation itself: leave runs past the certificate
                start_date, end_date = "2026-08-04", "2026-09-11"
                cert_start, cert_end = "2026-08-04", "2026-08-31"
            conn.execute(
                """
                INSERT INTO leave_requests
                    (employee_id, leave_type, start_date, end_date, leave_year, status,
                     working_day_count, cert_start_date, cert_end_date, review_flag)
                VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    "sick" if leave_type == "sick" else "annual",
                    start_date,
                    end_date,
                    DEMO_YEAR,
                    float(last - first + 1),
                    cert_start,
                    cert_end,
                    code,
                ),
            )
            counts["leave_requests"] += 1

    # --- replacements ------------------------------------------------------
    for person in DEMO_EMPLOYEES:
        for index, cell in enumerate(person["cells"]):
            iso = DEMO_WEEK_DATES[index]
            if _issue_code(cell) == "vacancy_unstaffed":
                conn.execute(
                    """
                    INSERT INTO replacement_assignments
                        (work_date, shift, zone, absent_employee_id, status, reason)
                    VALUES (?, 'day', ?, ?, 'vacancy', '대체 미배치')
                    """,
                    (iso, person["zone"], employee_ids[person["name"]]),
                )
                counts["replacement_assignments"] += 1
            elif cell["type"] == "replacement":
                covered = cell.get("punch", "").replace(" 대체", "").strip()
                conn.execute(
                    """
                    INSERT INTO replacement_assignments
                        (work_date, shift, zone, absent_employee_id, substitute_employee_id,
                         status, assigned_by)
                    VALUES (?, 'day', ?, ?, ?, 'assigned', 'demo-seed')
                    """,
                    (iso, person["zone"], employee_ids.get(covered), employee_ids[person["name"]]),
                )
                counts["replacement_assignments"] += 1

    # --- one document and one note, so those views are not empty -----------
    kim = employee_ids["김가람"]
    cur = conn.execute(
        """
        INSERT INTO documents (employee_id, entity_type, doc_type, title,
                               original_filename, stored_path, mime_type, uploaded_by)
        VALUES (?, 'leave_request', 'medical_certificate', '진단서 (8/4~8/31)',
                'demo-certificate.pdf', 'uploads/demo-certificate.pdf', 'application/pdf', 'demo-seed')
        """,
        (kim,),
    )
    counts["documents"] += 1
    conn.execute(
        "UPDATE leave_requests SET evidence_document_id = ? "
        "WHERE employee_id = ? AND leave_type = 'sick'",
        (int(cur.lastrowid), kim),
    )
    conn.execute(
        """
        INSERT INTO notes (employee_id, work_date, category, body, author)
        VALUES (?, ?, 'leave', '진단서 기간이 병가 신청기간보다 짧습니다. 추가 증빙 필요.', 'demo-seed')
        """,
        (kim, DEMO_TODAY),
    )
    counts["notes"] += 1

    _seed_rest_of_month(conn, employee_ids, counts)
    summary.counts = counts


def _seed_rest_of_month(
    conn: sqlite3.Connection, employee_ids: dict[str, int], counts: dict[str, int]
) -> None:
    """Fill the month outside the fixed demo week.

    The monthly view aggregates the whole month, but only one week is described
    in detail. The remaining days are seeded from DEMO_MONTH_STATS so the
    monthly view stays populated, deterministically and without a second
    dataset: the counts are turned back into real attendance rows, and the API
    then derives the aggregate from those rows.

    In-week days are NOT seeded here — they already have real rows, and the
    aggregate is derived from them. That makes the monthly view agree with the
    weekly view; the previous hand-written mock did not (8/12–8/14 showed a
    leave but omitted a concurrent sick leave).
    """
    names = [p["name"] for p in DEMO_EMPLOYEES]
    week_days = {int(iso[-2:]) for iso in DEMO_WEEK_DATES}

    for day_str, stats in sorted(DEMO_MONTH_STATS.items(), key=lambda kv: int(kv[0])):
        day = int(day_str)
        if day in week_days:
            continue
        iso = f"{DEMO_YEAR}-{DEMO_MONTH:02d}-{day:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO site_calendar (calendar_date, day_type, is_working) "
            "VALUES (?, 'working', 1)",
            (iso,),
        )
        counts["site_calendar"] += 1

        # deterministic, stable assignment of people to the day's counts
        picked = 0
        for category, status, flag in (
            ("leave", "leave", None),
            ("sick", "sick_leave", None),
            ("issue", "normal", "other"),
        ):
            for _ in range(int(stats.get(category, 0))):
                name = names[(day * 3 + picked) % len(names)]
                picked += 1
                conn.execute(
                    """
                    INSERT OR IGNORE INTO attendance_days
                        (employee_id, work_date, status, scheduled_start, scheduled_end,
                         source, review_flag)
                    VALUES (?, ?, ?, ?, ?, 'derived', ?)
                    """,
                    (employee_ids[name], iso, status, SCHEDULED_START, SCHEDULED_END, flag),
                )
                counts["attendance_days"] += 1

        for _ in range(int(stats.get("replace", 0))):
            absent = names[(day * 3 + picked) % len(names)]
            picked += 1
            substitute = names[(day * 3 + picked) % len(names)]
            picked += 1
            if absent == substitute:
                continue
            conn.execute(
                """
                INSERT INTO replacement_assignments
                    (work_date, shift, absent_employee_id, substitute_employee_id,
                     status, assigned_by)
                VALUES (?, 'day', ?, ?, 'assigned', 'demo-seed')
                """,
                (iso, employee_ids[absent], employee_ids[substitute]),
            )
            counts["replacement_assignments"] += 1


def _contiguous(cells: list[dict], types: set[str]) -> list[tuple[str, int, int, list[str | None]]]:
    """Group consecutive leave/sick cells into single leave requests."""
    runs: list[tuple[str, int, int, list[str | None]]] = []
    start: int | None = None
    kind: str | None = None
    codes: list[str | None] = []
    for index, cell in enumerate(cells + [{"type": "__end__"}]):
        cell_type = cell["type"]
        if cell_type in types:
            if start is None:
                start, kind, codes = index, cell_type, []
            codes.append(_issue_code(cell))
        else:
            if start is not None and kind is not None:
                runs.append((kind, start, index - 1, codes))
            start, kind, codes = None, None, []
    return runs
