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
 …7134 tokens truncated…  old_att=conn.execute("SELECT * FROM attendance_days WHERE employee_id=? AND work_date=?",(employee_id,work_date)).fetchone()
    if old_att and old_att["confirmed_at"] and not active: raise SafetyError("unrelated confirmed attendance already exists")
    if active: conn.execute("UPDATE manual_attendance_adjustments SET status='superseded',ended_at=?,ended_by=?,end_reason=? WHERE id=?",(now(),actor,reason,active["id"]))
    stamp=now()
    conn.execute("INSERT INTO attendance_days(employee_id,work_date,status,actual_in_at,actual_out_at,source,confirmed_at,confirmed_by,review_flag,review_note) VALUES(?,?,?,?,?,'manual',?,?,NULL,?) ON CONFLICT(employee_id,work_date) DO UPDATE SET status=excluded.status,actual_in_at=excluded.actual_in_at,actual_out_at=excluded.actual_out_at,source='manual',confirmed_at=excluded.confirmed_at,confirmed_by=excluded.confirmed_by,review_flag=NULL,review_note=excluded.review_note,last_import_run_id=NULL",
      (employee_id,work_date,resulting_status,recognized_in_at,recognized_out_at,stamp,actor,reason))
    attendance_id=conn.execute("SELECT id FROM attendance_days WHERE employee_id=? AND work_date=?",(employee_id,work_date)).fetchone()[0]
    aid=conn.execute("INSERT INTO manual_attendance_adjustments(employee_id,work_date,recognized_in_at,recognized_out_at,resulting_status,reason,reference_note,supersedes_adjustment_id,attendance_id,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
      (employee_id,work_date,recognized_in_at,recognized_out_at,resulting_status,reason,reference_note,supersedes_id,attendance_id,actor)).lastrowid
    if active:conn.execute("UPDATE manual_attendance_adjustments SET superseded_by_adjustment_id=? WHERE id=?",(aid,active["id"]))
    after=rowdict(conn.execute("SELECT * FROM manual_attendance_adjustments WHERE id=?",(aid,)).fetchone());audit(conn,"attendance.manual_adjust", "manual_attendance_adjustments",aid,dict(active) if active else None,after,reason,actor);return after

def end_adjustment(conn,adjustment_id,status,reason,actor="operator"):
    if status not in {"cancelled","voided"}: raise SafetyError("invalid adjustment end status")
    row=conn.execute("SELECT * FROM manual_attendance_adjustments WHERE id=? AND status='active'",(adjustment_id,)).fetchone()
    if not row: raise SafetyError("active adjustment not found")
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["work_date"],row["work_date"])
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    attendance=conn.execute("SELECT * FROM attendance_days WHERE id=?",(row["attendance_id"],)).fetchone()
    # Ownership guard: only remove this adjustment's exact manual projection.
    owned=attendance and attendance["employee_id"]==row["employee_id"] and attendance["work_date"]==row["work_date"] and attendance["source"]=="manual" and attendance["confirmed_by"]==row["created_by"] and attendance["status"]==row["resulting_status"] and attendance["actual_in_at"]==row["recognized_in_at"] and attendance["actual_out_at"]==row["recognized_out_at"]
    conn.execute("UPDATE manual_attendance_adjustments SET status=?,ended_at=?,ended_by=?,end_reason=? WHERE id=?",(status,now(),actor,reason,adjustment_id))
    if owned:
        punches=conn.execute("SELECT COUNT(*) FROM punch_events WHERE employee_id=? AND work_date=? AND rolled_back_at IS NULL",(row["employee_id"],row["work_date"])).fetchone()[0]
        conn.execute("UPDATE attendance_days SET confirmed_at=NULL,confirmed_by=NULL WHERE id=?",(attendance["id"],))
        if punches:
            from app.services.xls_pipeline import derive_attendance
            derive_attendance(conn,[(row["employee_id"],row["work_date"])])
        else: conn.execute("UPDATE attendance_days SET status='unknown',actual_in_at=NULL,actual_out_at=NULL,source='manual',review_flag='manual_review',review_note=?,last_import_run_id=NULL WHERE id=?",("수동 근무 인정이 종료되어 확인이 필요합니다.",attendance["id"]))
    updated=rowdict(conn.execute("SELECT * FROM manual_attendance_adjustments WHERE id=?",(adjustment_id,)).fetchone());audit(conn,f"attendance.manual_{status}","manual_attendance_adjustments",adjustment_id,dict(row),updated,reason,actor);return updated

def create_schedule(conn,*,employee_id,effective_from,effective_to,weekday_mask,expected_start_time=None,expected_end_time=None,actor="operator"):
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,effective_from,effective_to)
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    _validate_employee_date(conn,employee_id,effective_from)
    if effective_to:
        _validate_employee_date(conn,employee_id,effective_to)
    if effective_to and effective_from>effective_to: raise SafetyError("schedule start must not follow end")
    overlap=conn.execute("SELECT id FROM employee_work_schedules WHERE employee_id=? AND status='active' AND effective_from<=COALESCE(?, '9999-12-31') AND COALESCE(effective_to,'9999-12-31')>=?",(employee_id,effective_to,effective_from)).fetchone()
    if overlap: raise SafetyError("schedule period overlaps an active schedule")
    sid=conn.execute("INSERT INTO employee_work_schedules(employee_id,effective_from,effective_to,weekday_mask,expected_start_time,expected_end_time,created_by) VALUES(?,?,?,?,?,?,?)",(employee_id,effective_from,effective_to,weekday_mask,expected_start_time,expected_end_time,actor)).lastrowid
    result=rowdict(conn.execute("SELECT * FROM employee_work_schedules WHERE id=?",(sid,)).fetchone());audit(conn,"schedule.create","employee_work_schedules",sid,None,result,"schedule created",actor);return result

def retire_schedule(conn,schedule_id,reason,actor="operator"):
    if not (reason or "").strip(): raise SafetyError("reason is required")
    row=conn.execute("SELECT * FROM employee_work_schedules WHERE id=? AND status='active'",(schedule_id,)).fetchone()
    if not row: raise SafetyError("active schedule not found")
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["effective_from"],row["effective_to"])
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    conn.execute("UPDATE employee_work_schedules SET status='retired',retired_at=?,retired_by=? WHERE id=?",(now(),actor,schedule_id))
    updated=rowdict(conn.execute("SELECT * FROM employee_work_schedules WHERE id=?",(schedule_id,)).fetchone())
    audit(conn,"schedule.retire","employee_work_schedules",schedule_id,dict(row),updated,reason,actor)
    return updated

def set_schedule_date(conn,*,employee_id,work_date,is_scheduled,expected_start_time=None,expected_end_time=None,label=None,actor="operator",supersedes_id=None):
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,work_date,work_date)
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    _validate_employee_date(conn,employee_id,work_date)
    active=conn.execute("SELECT * FROM employee_schedule_dates WHERE employee_id=? AND work_date=? AND status='active'",(employee_id,work_date)).fetchone()
    if active and active["id"]!=supersedes_id: raise SafetyError("an active date override already exists")
    if supersedes_id and (not active or active["id"]!=supersedes_id): raise SafetyError("only active override may be superseded")
    if active:conn.execute("UPDATE employee_schedule_dates SET status='superseded' WHERE id=?",(active["id"],))
    oid=conn.execute("INSERT INTO employee_schedule_dates(employee_id,work_date,is_scheduled,expected_start_time,expected_end_time,label,supersedes_date_id,created_by) VALUES(?,?,?,?,?,?,?,?)",(employee_id,work_date,int(is_scheduled),expected_start_time,expected_end_time,label,supersedes_id,actor)).lastrowid
    result=rowdict(conn.execute("SELECT * FROM employee_schedule_dates WHERE id=?",(oid,)).fetchone());audit(conn,"schedule.override","employee_schedule_dates",oid,dict(active) if active else None,result,"date override",actor);return result

def cancel_schedule_date(conn,override_id,reason,actor="operator"):
    if not (reason or "").strip(): raise SafetyError("reason is required")
    row=conn.execute("SELECT * FROM employee_schedule_dates WHERE id=? AND status='active'",(override_id,)).fetchone()
    if not row: raise SafetyError("active date override not found")
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["work_date"],row["work_date"])
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    conn.execute("UPDATE employee_schedule_dates SET status='cancelled' WHERE id=?",(override_id,))
    updated=rowdict(conn.execute("SELECT * FROM employee_schedule_dates WHERE id=?",(override_id,)).fetchone())
    audit(conn,"schedule.override_cancel","employee_schedule_dates",override_id,dict(row),updated,reason,actor)
    return updated

def resolve_schedule(conn,employee_id,work_date):
    employee=conn.execute("SELECT hire_date,end_date FROM employees WHERE id=?",(employee_id,)).fetchone()
    if not employee: raise SafetyError("employee not found")
    if work_date<employee["hire_date"] or (employee["end_date"] and work_date>employee["end_date"]):
        return {"isScheduled":False,"source":"employment_period","expectedStart":None,"expectedEnd":None,"evidenceId":None}
    override=conn.execute("SELECT * FROM employee_schedule_dates WHERE employee_id=? AND work_date=? AND status='active' ORDER BY id DESC LIMIT 1",(employee_id,work_date)).fetchone()
    if override:return {"isScheduled":bool(override["is_scheduled"]),"source":"employee_date_override","expectedStart":override["expected_start_time"],"expectedEnd":override["expected_end_time"],"evidenceId":override["id"]}
    schedule=conn.execute("SELECT * FROM employee_work_schedules WHERE employee_id=? AND status='active' AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?) ORDER BY effective_from DESC,id DESC LIMIT 1",(employee_id,work_date,work_date)).fetchone()
    if schedule:
        scheduled=str(date.fromisoformat(work_date).weekday()) in set(schedule["weekday_mask"].split(","))
        return {"isScheduled":scheduled,"source":"employee_schedule","expectedStart":schedule["expected_start_time"],"expectedEnd":schedule["expected_end_time"],"evidenceId":schedule["id"]}
    calendar=conn.execute("SELECT * FROM site_calendar WHERE calendar_date=?",(work_date,)).fetchone()
    is_working=bool(calendar["is_working"]) if calendar else date.fromisoformat(work_date).weekday()<5
    return {"isScheduled":is_working,"source":"site_calendar","expectedStart":None,"expectedEnd":None,"evidenceId":calendar["id"] if calendar else None}

def _source_observation(conn,code,work_date,import_run_id,observed,expected,scheduled,measurement):
    conn.execute("INSERT OR IGNORE INTO source_quality_observations(observation_code,work_date,import_run_id,observed_value,expected_value,scheduled_worker_count,rule_version,measurement_json) VALUES(?,?,?,?,?,?,'1',?)",
      (code,work_date,import_run_id,observed,expected,scheduled,json.dumps(measurement,sort_keys=True)))
    return conn.execute("SELECT id FROM source_quality_observations WHERE observation_code=? AND work_date=? AND IFNULL(import_run_id,-1)=IFNULL(?,-1) AND rule_version='1'",(code,work_date,import_run_id)).fetchone()[0]

def reconcile(conn,start,end,actor="system"):
    created=[]
    employees=conn.execute("SELECT * FROM employees WHERE hire_date<=? AND (end_date IS NULL OR end_date>=?)",(end,start)).fetchall()
    day=date.fromisoformat(start);last=date.fromisoformat(end)
    while day<=last:
        iso=day.isoformat(); scheduled=[]
        for e in employees:
            if resolve_schedule(conn,e["id"],iso)["isScheduled"]:scheduled.append(e)
        punches=conn.execute("SELECT * FROM punch_events WHERE work_date=? AND rolled_back_at IS NULL ORDER BY id",(iso,)).fetchall()
        coverage=conn.execute("SELECT d.*,r.source_filename FROM import_run_days d JOIN import_runs r ON r.id=d.import_run_id WHERE d.work_date=? AND r.status='applied' ORDER BY d.id DESC LIMIT 1",(iso,)).fetchone()
        expected_run=conn.execute("SELECT * FROM import_runs WHERE status='applied' AND period_start<=? AND period_end>=? ORDER BY id DESC LIMIT 1",(iso,iso)).fetchone()
        source_wide_problem=False
        if scheduled and coverage and coverage["raw_punch_count"]==0:
            source_wide_problem=True
            oid=_source_observation(conn,"covered_but_zero_events",iso,coverage["import_run_id"],0,len(scheduled),len(scheduled),{"coverageStatus":coverage["coverage_status"]})
            created.append(ensure_exception(conn,code="covered_but_zero_events",severity="review",scope="source",work_date=iso,import_run_id=coverage["import_run_id"],summary="가져온 자료에 전체 지문 기록이 없습니다",source_ref=f"coverage:{coverage['import_run_id']}",evidence=[{"evidence_type":"fingerprint_import","entity_type":"import_runs","entity_id":coverage["import_run_id"],"import_run_id":coverage["import_run_id"]},{"evidence_type":"source_quality_measurement","entity_type":"source_quality_observations","entity_id":oid}],actor=actor))
        elif scheduled and expected_run and not coverage:
            source_wide_problem=True
            oid=_source_observation(conn,"expected_period_not_covered",iso,expected_run["id"],None,len(scheduled),len(scheduled),{"periodStart":expected_run["period_start"],"periodEnd":expected_run["period_end"]})
            created.append(ensure_exception(conn,code="expected_period_not_covered",severity="review",scope="source",work_date=iso,import_run_id=expected_run["id"],summary="예상된 근무일이 가져온 자료 범위에 포함되지 않았습니다",source_ref=f"coverage:{expected_run['id']}",evidence=[{"evidence_type":"fingerprint_import","entity_type":"import_runs","entity_id":expected_run["id"],"import_run_id":expected_run["id"]},{"evidence_type":"source_quality_measurement","entity_type":"source_quality_observations","entity_id":oid}],actor=actor))
        observed_workers={p["employee_id"] for p in punches if p["employee_id"] is not None}
        if coverage and len(scheduled)>=4 and 0<len(observed_workers)*2<len(scheduled):
            oid=_source_observation(conn,"source_quality_drop",iso,coverage["import_run_id"],len(observed_workers),len(scheduled),len(scheduled),{"activePunches":len(punches),"observedWorkers":len(observed_workers)})
            created.append(ensure_exception(conn,code="source_quality_drop",severity="review",scope="source",work_date=iso,import_run_id=coverage["import_run_id"],summary="예정 인원에 비해 지문 기록 인원이 크게 적습니다",source_ref=f"coverage:{coverage['import_run_id']}",evidence=[{"evidence_type":"fingerprint_import","entity_type":"import_runs","entity_id":coverage["import_run_id"],"import_run_id":coverage["import_run_id"]},{"evidence_type":"source_quality_measurement","entity_type":"source_quality_observations","entity_id":oid}],actor=actor))
        for e in scheduled:
            ep=[p for p in punches if p["employee_id"]==e["id"]]
            if not ep and not source_wide_problem:
                schedule=resolve_schedule(conn,e["id"],iso)
                evidence=[{"evidence_type":"employee_work_schedule","entity_type":schedule["source"],"entity_id":schedule["evidenceId"],"reference_text":f"{schedule['source']}:{schedule['evidenceId'] or iso}"}]
                if coverage:evidence.append({"evidence_type":"fingerprint_import","entity_type":"import_runs","entity_id":coverage["import_run_id"],"import_run_id":coverage["import_run_id"]})
                created.append(ensure_exception(conn,code="scheduled_no_punch",severity="review",scope="employee",employee_id=e["id"],work_date=iso,summary="예정 근무일에 기록된 지문이 없습니다",detail="결근으로 판정하지 않으며 관리자 확인이 필요합니다.",evidence=evidence,actor=actor))
            elif len(ep)==1:
                created.append(ensure_exception(conn,code="incomplete_day",severity="review",scope="employee",employee_id=e["id"],work_date=iso,import_run_id=ep[0]["active_import_run_id"],summary="지문 기록이 한 건뿐입니다",evidence=[{"evidence_type":"fingerprint_punch","entity_type":"punch_events","entity_id":ep[0]["id"],"punch_event_id":ep[0]["id"]}],actor=actor))
        day=date.fromordinal(day.toordinal()+1)
    # Promote leave findings without losing the actual employee/date evidence.
    from app.services import leave_operations, work_calendar
    for leave in leave_operations.list_leave(conn,None,start,end):
        for code in leave.get("findings",[]):
            if code=="leave_attendance_conflict":
                period_start=max(start,leave["startDate"]);period_end=min(end,leave["endDate"])
                for iso in work_calendar.working_dates(conn,period_start,period_end):
                    if leave_operations.approved_leave_coverage(conn,leave["employeeId"],iso)["coverage"]!="full":continue
                    punches=conn.execute("SELECT id,active_import_run_id FROM punch_events WHERE employee_id=? AND work_date=? AND rolled_back_at IS NULL ORDER BY id",(leave["employeeId"],iso)).fetchall()
                    if not punches:continue
                    evidence=[{"evidence_type":"approved_leave","entity_type":"leave_requests","entity_id":leave["id"]}]+[{"evidence_type":"fingerprint_punch","entity_type":"punch_events","entity_id":p["id"],"punch_event_id":p["id"],"import_run_id":p["active_import_run_id"]} for p in punches]
                    created.append(ensure_exception(conn,code=code,severity="review",scope="employee",employee_id=leave["employeeId"],work_date=iso,summary=code,evidence=evidence,actor=actor))
            else:
                created.append(ensure_exception(conn,code=code,severity="review",scope="employee",employee_id=leave["employeeId"],work_date=leave["startDate"],summary=code,evidence=[{"evidence_type":"approved_leave","entity_type":"leave_requests","entity_id":leave["id"]}],actor=actor))
    return created

def operations_read_model(conn,start,end,**filters):
    reconcile(conn,start,end)
    return {"startDate":start,"endDate":end,"exceptions":list_exceptions(conn,start=start,end=end,**filters),"sourceQuality":[dict(r) for r in conn.execute("SELECT * FROM source_quality_observations WHERE work_date BETWEEN ? AND ? ORDER BY id",(start,end))],"manualAdjustments":[dict(r) for r in conn.execute("SELECT * FROM manual_attendance_adjustments WHERE work_date BETWEEN ? AND ? ORDER BY id",(start,end))]}
