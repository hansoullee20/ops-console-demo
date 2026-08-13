"""Deterministic operational leave rules and audit trail."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.services import work_calendar

API_TO_DB = {
    "annual_leave": "annual",
    "half_day": "half_day",
    "sick_leave": "sick",
    "other_authorized_leave": "other",
}
DB_TO_API = {value: key for key, value in API_TO_DB.items()}
BLOCKING_STATUSES = ("requested", "approved")


class LeaveError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _employee(conn: sqlite3.Connection, employee_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if row is None:
        raise LeaveError("직원을 찾을 수 없습니다.")
    return row


def _validate_employment(employee: sqlite3.Row, start_date: str, end_date: str) -> None:
    if start_date < employee["hire_date"]:
        raise LeaveError("입사일 이전에는 휴가를 등록할 수 없습니다.")
    if employee["end_date"] and end_date > employee["end_date"]:
        raise LeaveError("퇴사일 이후에는 휴가를 등록할 수 없습니다.")


def _portion_set(leave_type: str, half_day_period: str | None) -> set[str]:
    if leave_type == "half_day":
        return {half_day_period or ""}
    return {"am", "pm"}


def _assert_no_overlap(
    conn: sqlite3.Connection, employee_id: int, start_date: str, end_date: str,
    leave_type: str, half_day_period: str | None, exclude_id: int | None = None,
) -> None:
    rows = conn.execute(
        """SELECT id, leave_type, half_day_period, start_date, end_date
             FROM leave_requests
            WHERE employee_id = ? AND status IN ('requested','approved')
              AND start_date <= ? AND end_date >= ?
              AND (? IS NULL OR id != ?)""",
        (employee_id, end_date, start_date, exclude_id, exclude_id),
    ).fetchall()
    new_portions = _portion_set(leave_type, half_day_period)
    for row in rows:
        overlap_start = max(start_date, row["start_date"])
        overlap_end = min(end_date, row["end_date"])
        for iso in work_calendar.dates_between(overlap_start, overlap_end):
            if not work_calendar.is_working_day(conn, iso):
                continue
            old_portions = _portion_set(row["leave_type"], row["half_day_period"])
            if new_portions & old_portions:
                raise LeaveError("같은 직원의 기존 휴가 기간과 겹칩니다.")


def _audit(conn: sqlite3.Connection, action: str, leave_id: int, actor: str,
           before: dict | None, after: dict | None, reason: str | None) -> None:
    conn.execute(
        """INSERT INTO audit_log
               (actor_type, actor_id, action, entity_type, entity_id,
                before_json, after_json, reason)
           VALUES ('user', ?, ?, 'leave_requests', ?, ?, ?, ?)""",
        (actor, action, leave_id,
         json.dumps(before, ensure_ascii=False, sort_keys=True) if before else None,
         json.dumps(after, ensure_ascii=False, sort_keys=True) if after else None,
         reason),
    )


def _normalize_input(leave_type: str, portion: str) -> tuple[str, str | None]:
    if leave_type not in API_TO_DB:
        raise LeaveError("지원하지 않는 휴가 종류입니다.")
    db_type = API_TO_DB[leave_type]
    if db_type == "half_day":
        if portion not in {"am", "pm"}:
            raise LeaveError("반차는 오전 또는 오후를 선택해야 합니다.")
        return db_type, portion
    if portion != "full":
        raise LeaveError("반일 구분은 반차에만 사용할 수 있습니다.")
    return db_type, None


def _finding(row: sqlite3.Row) -> str | None:
    if row["leave_type"] == "sick" and row["evidence_received"]:
        if not row["cert_start_date"] or not row["cert_end_date"]:
            return "sick_leave_evidence_mismatch"
        if row["cert_start_date"] != row["start_date"] or row["cert_end_date"] != row["end_date"]:
            return "sick_leave_evidence_mismatch"
    return row["review_flag"]


def serialize(row: sqlite3.Row) -> dict:
    finding = _finding(row)
    return {
        "id": row["id"], "employeeId": row["employee_id"],
        "employee": row["employee_name"] if "employee_name" in row.keys() else None,
        "leaveType": DB_TO_API.get(row["leave_type"], "other_authorized_leave"),
        "portion": row["half_day_period"] or "full",
        "startDate": row["start_date"], "endDate": row["end_date"],
        "calculatedDays": row["working_day_count"], "leaveYear": row["leave_year"],
        "status": row["status"], "reason": row["reason"],
        "evidenceReceived": bool(row["evidence_received"]),
        "evidenceStartDate": row["cert_start_date"],
        "evidenceEndDate": row["cert_end_date"],
        "evidenceNote": row["evidence_note"],
        "evidenceCheckedDate": row["evidence_checked_date"],
        "finding": finding, "findings": [finding] if finding else [],
        "approvedAt": row["approved_at"],
        "cancelledAt": row["cancelled_at"], "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def approved_leave_coverage(conn: sqlite3.Connection, employee_id: int, iso: str) -> dict:
    """Resolve approved leave for one employee/workday without row-order assumptions."""
    if not work_calendar.is_working_day(conn, iso):
        return {"coverage": "none", "leaveType": None, "rows": []}
    rows = conn.execute(
        """SELECT * FROM leave_requests WHERE employee_id=? AND status='approved'
             AND start_date<=? AND end_date>=? ORDER BY id""", (employee_id, iso, iso)
    ).fetchall()
    full = [row for row in rows if row["leave_type"] != "half_day"]
    portions = {row["half_day_period"] for row in rows if row["leave_type"] == "half_day"}
    if full:
        chosen = full[-1]
        return {"coverage": "full", "leaveType": chosen["leave_type"], "rows": rows}
    if {"am", "pm"}.issubset(portions):
        return {"coverage": "full", "leaveType": "annual", "rows": rows}
    if "am" in portions or "pm" in portions:
        return {"coverage": "am" if "am" in portions else "pm", "leaveType": "half_day", "rows": rows}
    return {"coverage": "none", "leaveType": None, "rows": rows}


def list_leave(conn: sqlite3.Connection, year: int | None = None,
               month_start: str | None = None, month_end: str | None = None) -> list[dict]:
    clauses, params = [], []
    if year:
        clauses.append("l.leave_year = ?"); params.append(year)
    if month_start and month_end:
        clauses.append("l.start_date <= ? AND l.end_date >= ?")
        params.extend((month_end, month_start))
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"""SELECT l.*, e.name AS employee_name FROM leave_requests l
              JOIN employees e ON e.id = l.employee_id {where}
             ORDER BY l.start_date, l.id""", params,
    ).fetchall()
    result = []
    for row in rows:
        item = serialize(row)
        if row["status"] == "approved":
            conflict = any(
                approved_leave_coverage(conn, row["employee_id"], iso)["coverage"] == "full"
                and conn.execute("SELECT 1 FROM punch_events WHERE employee_id=? AND work_date=? AND rolled_back_at IS NULL LIMIT 1", (row["employee_id"], iso)).fetchone()
                for iso in work_calendar.working_dates(conn, row["start_date"], row["end_date"])
            )
            if conflict and "leave_attendance_conflict" not in item["findings"]:
                item["findings"].append("leave_attendance_conflict")
        item["finding"] = item["findings"][0] if item["findings"] else None
        result.append(item)
    return result


def create_leave(conn: sqlite3.Connection, *, employee_id: int, leave_type: str,
                 start_date: str, end_date: str, portion: str = "full",
                 reason: str | None = None, evidence_received: bool = False,
                 evidence_start_date: str | None = None,
                 evidence_end_date: str | None = None,
                 evidence_note: str | None = None,
                 evidence_checked_date: str | None = None,
                 actor: str = "operator") -> dict:
    from app.services.month_close import MonthCloseError, assert_range_open
    try: assert_range_open(conn, start_date, end_date)
    except MonthCloseError as exc: raise LeaveError(str(exc)) from exc
    if start_date[:4] != end_date[:4]:
        raise LeaveError("cross-year leave must be registered as one request per year")
    employee = _employee(conn, employee_id)
    _validate_employment(employee, start_date, end_date)
    db_type, half = _normalize_input(leave_type, portion)
    try:
        days = work_calendar.leave_days(conn, start_date, end_date, half or "full")
    except work_calendar.CalendarError as exc:
        raise LeaveError(str(exc)) from exc
    if days <= 0:
        raise LeaveError("선택한 기간에 근무일이 없습니다.")
    _assert_no_overlap(conn, employee_id, start_date, end_date, db_type, half)
    if evidence_end_date and evidence_start_date and evidence_end_date < evidence_start_date:
        raise LeaveError("증빙 종료일은 시작일보다 빠를 수 없습니다.")
    cursor = conn.execute(
        """INSERT INTO leave_requests
               (employee_id, leave_type, half_day_period, start_date, end_date,
                working_day_count, leave_year, status, reason, evidence_received,
                cert_start_date, cert_end_date, evidence_note, evidence_checked_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'requested', ?, ?, ?, ?, ?, ?)""",
        (employee_id, db_type, half, start_date, end_date, days, int(start_date[:4]),
         reason, int(evidence_received), evidence_start_date, evidence_end_date,
         evidence_note, evidence_checked_date),
    )
    leave_id = int(cursor.lastrowid)
    row = conn.execute("SELECT * FROM leave_requests WHERE id=?", (leave_id,)).fetchone()
    _audit(conn, "leave.create", leave_id, actor, None, dict(row), reason)
    return serialize(row)


def _get(conn: sqlite3.Connection, leave_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM leave_requests WHERE id=?", (leave_id,)).fetchone()
    if row is None:
        raise LeaveError("휴가 기록을 찾을 수 없습니다.")
    return row


def _sync_balance(conn: sqlite3.Connection, employee_id: int, year: int) -> None:
    used = conn.execute(
        """SELECT COALESCE(SUM(working_day_count),0) FROM leave_requests
            WHERE employee_id=? AND leave_year=? AND status='approved'
              AND leave_type IN ('annual','half_day')""", (employee_id, year),
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO leave_balances(employee_id,leave_year,used_days)
           VALUES(?,?,?) ON CONFLICT(employee_id,leave_year)
           DO UPDATE SET used_days=excluded.used_days""", (employee_id, year, used),
    )


def balance(conn: sqlite3.Connection, employee_id: int, year: int) -> dict:
    row = conn.execute(
        "SELECT granted_days,carried_days FROM leave_balances WHERE employee_id=? AND leave_year=?",
        (employee_id, year),
    ).fetchone()
    granted = float(row["granted_days"] if row else 0)
    carried = float(row["carried_days"] if row else 0)
    used = float(conn.execute(
        """SELECT COALESCE(SUM(working_day_count),0) FROM leave_requests
            WHERE employee_id=? AND leave_year=? AND status='approved'
              AND leave_type IN ('annual','half_day')""", (employee_id, year),
    ).fetchone()[0])
    return {"employeeId": employee_id, "year": year, "entitlement": granted + carried,
            "used": used, "remaining": granted + carried - used}


def _sync_attendance(conn: sqlite3.Connection, employee_id: int, dates: set[str]) -> None:
    owned_flags = {
        None, "incomplete_day", "import_rolled_back",
        "leave_attendance_conflict", "partial_leave_review",
    }
    for iso in sorted(dates):
        coverage = approved_leave_coverage(conn, employee_id, iso)
        punch_count = conn.execute(
            "SELECT COUNT(*) FROM punch_events WHERE employee_id=? AND work_date=? AND rolled_back_at IS NULL",
            (employee_id, iso),
        ).fetchone()[0]
        existing = conn.execute(
            "SELECT id,confirmed_at,review_flag,source FROM attendance_days "
            "WHERE employee_id=? AND work_date=?", (employee_id, iso),
        ).fetchone()
        if existing and existing["confirmed_at"]:
            continue
        if coverage["coverage"] in {"am", "pm"}:
            status, flag, note = "half_day", "partial_leave_review", "반차와 지문 시간을 관리자가 확인해야 합니다."
        elif coverage["coverage"] == "full":
            status = "sick_leave" if coverage["leaveType"] == "sick" else "leave"
            flag = "leave_attendance_conflict" if punch_count else None
            note = "승인 휴가일에 활성 지문이 있습니다." if punch_count else None
        elif punch_count >= 2:
            status, flag, note = "normal", None, None
        elif punch_count == 1:
            status, flag, note = "unknown", "incomplete_day", "지문 기록이 한 건뿐입니다."
        else:
            status = "unknown"
            flag = "import_rolled_back" if existing and existing["source"] == "fingerprint" else None
            note = "근태 근거가 부족하며 결근으로 자동 판정하지 않습니다."
        if existing and existing["review_flag"] not in owned_flags:
            flag = existing["review_flag"]
        if existing:
            conn.execute(
                "UPDATE attendance_days SET status=?,review_flag=?,review_note=? WHERE id=?",
                (status, flag, note, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO attendance_days(employee_id,work_date,status,review_flag,review_note) VALUES(?,?,?,?,?)",
                (employee_id, iso, status, flag, note),
            )


def approve_leave(conn: sqlite3.Connection, leave_id: int, *, actor: str = "operator") -> dict:
    row = _get(conn, leave_id)
    from app.services.month_close import MonthCloseError, assert_range_open
    try: assert_range_open(conn, row["start_date"], row["end_date"])
    except MonthCloseError as exc: raise LeaveError(str(exc)) from exc
    if row["status"] != "requested":
        raise LeaveError("승인 대기 중인 휴가만 승인할 수 있습니다.")
    before = dict(row); now = _now()
    conn.execute("UPDATE leave_requests SET status='approved',approved_by=?,approved_at=?,updated_at=? WHERE id=?",
                 (actor, now, now, leave_id))
    after = dict(_get(conn, leave_id)); _audit(conn, "leave.approve", leave_id, actor, before, after, "휴가 승인")
    _sync_balance(conn, row["employee_id"], row["leave_year"])
    _sync_attendance(conn, row["employee_id"], set(work_calendar.working_dates(conn, row["start_date"], row["end_date"])))
    return serialize(_get(conn, leave_id))


def correct_leave(conn: sqlite3.Connection, leave_id: int, *, employee_id: int,
                  leave_type: str, start_date: str, end_date: str, portion: str,
                  reason: str, evidence_received: bool = False,
                  evidence_start_date: str | None = None, evidence_end_date: str | None = None,
                  evidence_note: str | None = None, evidence_checked_date: str | None = None,
                  actor: str = "operator") -> dict:
    old = _get(conn, leave_id)
    from app.services.month_close import MonthCloseError, assert_range_open
    try:
        assert_range_open(conn, old["start_date"], old["end_date"])
        assert_range_open(conn, start_date, end_date)
    except MonthCloseError as exc: raise LeaveError(str(exc)) from exc
    if old["status"] in {"cancelled", "rejected"}:
        raise LeaveError("취소되거나 반려된 휴가는 정정할 수 없습니다.")
    if start_date[:4] != end_date[:4]:
        raise LeaveError("cross-year leave must be registered as one request per year")
    employee = _employee(conn, employee_id); _validate_employment(employee, start_date, end_date)
    db_type, half = _normalize_input(leave_type, portion)
    try:
        days = work_calendar.leave_days(conn, start_date, end_date, half or "full")
    except work_calendar.CalendarError as exc:
        raise LeaveError(str(exc)) from exc
    if days <= 0: raise LeaveError("선택한 기간에 근무일이 없습니다.")
    _assert_no_overlap(conn, employee_id, start_date, end_date, db_type, half, leave_id)
    if evidence_start_date and evidence_end_date and evidence_end_date < evidence_start_date:
        raise LeaveError("evidence end date cannot be before its start date")
    before = dict(old); now = _now()
    conn.execute(
        """UPDATE leave_requests SET employee_id=?,leave_type=?,half_day_period=?,
               start_date=?,end_date=?,working_day_count=?,leave_year=?,reason=?,
               evidence_received=?,cert_start_date=?,cert_end_date=?,evidence_note=?,
               evidence_checked_date=?,updated_at=? WHERE id=?""",
        (employee_id, db_type, half, start_date, end_date, days, int(start_date[:4]), reason,
         int(evidence_received), evidence_start_date, evidence_end_date, evidence_note,
         evidence_checked_date, now, leave_id),
    )
    after = dict(_get(conn, leave_id)); _audit(conn, "leave.correct", leave_id, actor, before, after, reason)
    for emp, year in {(old["employee_id"], old["leave_year"]), (employee_id, int(start_date[:4]))}:
        _sync_balance(conn, emp, year)
    if old["status"] == "approved":
        old_dates = set(work_calendar.working_dates(conn, old["start_date"], old["end_date"]))
        new_dates = set(work_calendar.working_dates(conn, start_date, end_date))
        _sync_attendance(conn, old["employee_id"], old_dates)
        _sync_attendance(conn, employee_id, new_dates)
    return serialize(_get(conn, leave_id))


def cancel_leave(conn: sqlite3.Connection, leave_id: int, reason: str, *, actor: str = "operator") -> dict:
    if len(reason.strip()) < 2: raise LeaveError("취소 이유를 입력하십시오.")
    row = _get(conn, leave_id)
    from app.services.month_close import MonthCloseError, assert_range_open
    try: assert_range_open(conn, row["start_date"], row["end_date"])
    except MonthCloseError as exc: raise LeaveError(str(exc)) from exc
    if row["status"] == "cancelled": raise LeaveError("이미 취소된 휴가입니다.")
    before = dict(row); now = _now()
    conn.execute("UPDATE leave_requests SET status='cancelled',cancelled_at=?,updated_at=? WHERE id=?", (now, now, leave_id))
    after = dict(_get(conn, leave_id)); _audit(conn, "leave.cancel", leave_id, actor, before, after, reason.strip())
    _sync_balance(conn, row["employee_id"], row["leave_year"])
    if row["status"] == "approved":
        _sync_attendance(conn, row["employee_id"], set(work_calendar.working_dates(conn, row["start_date"], row["end_date"])))
    return serialize(_get(conn, leave_id))
