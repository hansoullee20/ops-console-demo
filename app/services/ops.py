"""Read models for the operations views.

Everything the UI shows is assembled here from the database. The API and the
demo-snapshot exporter both call these functions, so the operational app and
the public demo are rendered by the same code over the same shapes.

Standard library only.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.services import presentation


def data_context(conn: sqlite3.Connection) -> dict[str, str | None]:
    """What kind of database is this, and (for a demo one) which week is fixed."""
    rows = conn.execute("SELECT key, value FROM app_meta").fetchall()
    meta = {row["key"]: row["value"] for row in rows}
    return {
        "data_context": meta.get("data_context", "unknown"),
        "demo_week_start": meta.get("demo_week_start"),
        "demo_today": meta.get("demo_today"),
    }


def _date_range(start: str, days: int) -> list[str]:
    year, month, day = (int(p) for p in start.split("-"))
    lengths = [31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    out = []
    for _ in range(days):
        out.append(f"{year:04d}-{month:02d}-{day:02d}")
        day += 1
        if day > lengths[month - 1]:
            day, month = 1, month + 1
            if month > 12:
                month, year = 1, year + 1
                lengths[1] = 29 if _leap(year) else 28
    return out


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def employees(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT e.id, e.employee_code, e.name, e.zone, e.hire_date, e.end_date, e.status,
               (SELECT slot_code FROM terminal_slots t
                 WHERE t.employee_id = e.id ORDER BY t.effective_from LIMIT 1) AS slot,
               (SELECT COALESCE(granted_days, 0) + COALESCE(carried_days, 0)
                       - COALESCE(used_days, 0)
                  FROM leave_balances b
                 WHERE b.employee_id = e.id ORDER BY b.leave_year DESC LIMIT 1) AS leave_left
          FROM employees e
         WHERE e.status <> 'terminated'
         ORDER BY e.id
        """
    ).fetchall()
    return presentation.rows_to_dicts(rows)


def _attendance_map(conn: sqlite3.Connection, dates: list[str]) -> dict[tuple[int, str], dict]:
    marks = ",".join("?" * len(dates))
    rows = conn.execute(
        f"SELECT * FROM attendance_days WHERE work_date IN ({marks})", dates
    ).fetchall()
    return {(row["employee_id"], row["work_date"]): dict(row) for row in rows}


def _punch_map(conn: sqlite3.Connection, dates: list[str]) -> dict[tuple[int, str], list[str]]:
    marks = ",".join("?" * len(dates))
    rows = conn.execute(
        f"""
        SELECT employee_id, work_date, punch_at
          FROM punch_events
         WHERE work_date IN ({marks}) AND employee_id IS NOT NULL
           AND rolled_back_at IS NULL
         ORDER BY punch_at
        """,
        dates,
    ).fetchall()
    out: dict[tuple[int, str], list[str]] = {}
    for row in rows:
        key = (row["employee_id"], row["work_date"])
        out.setdefault(key, []).append(row["punch_at"][11:16])
    return out


def _replacement_map(conn: sqlite3.Connection, dates: list[str]) -> dict[tuple[int, str], dict]:
    marks = ",".join("?" * len(dates))
    rows = conn.execute(
        f"""
        SELECT r.*, a.name AS absent_name, s.name AS substitute_name
          FROM replacement_assignments r
          LEFT JOIN employees a ON a.id = r.absent_employee_id
          LEFT JOIN employees s ON s.id = r.substitute_employee_id
         WHERE r.work_date IN ({marks}) AND r.status IN ('assigned', 'completed')
        """,
        dates,
    ).fetchall()
    out: dict[tuple[int, str], dict] = {}
    for row in rows:
        if row["substitute_employee_id"] is not None:
            entry = dict(row)
            entry["substitute_is_this_employee"] = True
            out[(row["substitute_employee_id"], row["work_date"])] = entry
    return out


def week_view(
    conn: sqlite3.Connection, start_date: str, today: str | None
) -> dict[str, Any]:
    """The weekly/daily operations grid: 7 days x every active employee."""
    dates = _date_range(start_date, 7)
    attendance = _attendance_map(conn, dates)
    punches = _punch_map(conn, dates)
    replacements = _replacement_map(conn, dates)

    people = []
    for person in employees(conn):
        cells = [
            presentation.build_cell(
                attendance.get((person["id"], iso)),
                punches.get((person["id"], iso), []),
                replacements.get((person["id"], iso)),
            )
            for iso in dates
        ]
        people.append(
            {
                "name": person["name"],
                "zone": person["zone"],
                "hire": person["hire_date"],
                "end": person["end_date"],
                "leave": _trim(person["leave_left"]),
                "slot": person["slot"],
                "state": presentation.employee_state(cells),
                "cells": cells,
            }
        )

    return {
        "days": presentation.build_days(dates, today),
        "dates": dates,
        "employees": people,
    }


def leave_cases(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Leave and sick-leave cases, with findings surfaced but never applied.

    If a medical certificate covers less than the requested sick leave, that is
    reported as a finding; neither period is silently altered (§7 Phase 4).
    """
    rows = conn.execute(
        """
        SELECT l.*, e.name FROM leave_requests l
          JOIN employees e ON e.id = l.employee_id
         ORDER BY l.start_date, e.id
        """
    ).fetchall()
    cases = []
    for row in rows:
        finding = None
        if row["cert_end_date"] and row["cert_end_date"] < row["end_date"]:
            finding = "증빙 기간이 신청 기간보다 짧습니다"
        cases.append(
            {
                "employee": row["name"],
                "zone": conn.execute(
                    "SELECT zone FROM employees WHERE id = ?", (row["employee_id"],)
                ).fetchone()["zone"],
                "leaveType": row["leave_type"],
                "startDate": row["start_date"],
                "endDate": row["end_date"],
                "status": row["status"],
                "workingDayCount": _trim(row["working_day_count"]),
                "certStartDate": row["cert_start_date"],
                "certEndDate": row["cert_end_date"],
                "finding": finding,
            }
        )
    return cases


def month_grid(conn: sqlite3.Connection, year: int, month: int) -> dict[str, Any]:
    """Per-employee marks for every day of the month (the 근태 tab).

    Derived from attendance_days and the site calendar. A day with no record is
    marked "기록 없음", never as attended and never as absence — missing data is
    not evidence of either (AI_BUILD_PLAN.md §3).
    """
    prefix = f"{year:04d}-{month:02d}-"
    days_in_month = [31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]

    non_working = {
        row["calendar_date"]
        for row in conn.execute(
            "SELECT calendar_date FROM site_calendar WHERE calendar_date LIKE ? AND is_working = 0",
            (prefix + "%",),
        )
    }

    rows = conn.execute(
        """
        SELECT a.employee_id, a.work_date, a.status, a.review_flag
          FROM attendance_days a WHERE a.work_date LIKE ?
        """,
        (prefix + "%",),
    ).fetchall()
    by_employee: dict[int, dict[str, dict]] = {}
    for row in rows:
        by_employee.setdefault(row["employee_id"], {})[row["work_date"]] = dict(row)

    people = []
    for person in employees(conn):
        marks = []
        issues = 0
        for day in range(1, days_in_month + 1):
            iso = f"{prefix}{day:02d}"
            record = by_employee.get(person["id"], {}).get(iso)
            if record is None:
                mark = "—" if iso in non_working else "·"
            elif record["review_flag"]:
                mark, issues = "!", issues + 1
            elif record["status"] in ("leave", "half_day"):
                mark = "휴"
            elif record["status"] == "sick_leave":
                mark = "병"
            elif record["status"] in ("off", "holiday"):
                mark = "—"
            elif record["status"] == "unknown":
                mark = "?"
            else:
                mark = "정"
            marks.append(mark)
        people.append({"name": person["name"], "marks": marks, "issues": issues})

    return {"year": year, "month": month, "days": days_in_month, "employees": people}


def month_stats(conn: sqlite3.Connection, year: int, month: int) -> dict[str, dict[str, int]]:
    """Per-day aggregate for the monthly calendar.

    Derived from the same rows the weekly view renders, so the two views agree.
    """
    prefix = f"{year:04d}-{month:02d}-"
    stats: dict[str, dict[str, int]] = {}

    def bump(iso: str, key: str) -> None:
        day = str(int(iso[8:10]))
        stats.setdefault(day, {})
        stats[day][key] = stats[day].get(key, 0) + 1

    for row in conn.execute(
        "SELECT work_date, status, review_flag FROM attendance_days WHERE work_date LIKE ?",
        (prefix + "%",),
    ):
        if row["review_flag"]:
            bump(row["work_date"], "issue")
        elif row["status"] in ("leave", "half_day"):
            bump(row["work_date"], "leave")
        elif row["status"] == "sick_leave":
            bump(row["work_date"], "sick")

    for row in conn.execute(
        "SELECT work_date FROM replacement_assignments "
        "WHERE work_date LIKE ? AND status IN ('assigned', 'completed')",
        (prefix + "%",),
    ):
        bump(row["work_date"], "replace")

    return {day: stats[day] for day in sorted(stats, key=int)}


def _trim(value: Any) -> Any:
    """9.0 -> 9, 8.5 -> 8.5, so the UI shows `9일` not `9.0일`."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
