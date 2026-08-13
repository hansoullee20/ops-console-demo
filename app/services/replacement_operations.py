"""Deterministic replacement staffing with PATCH-safe checklist updates."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.services import work_calendar

API_TO_DB = {"planned": "candidate", "confirmed": "assigned", "completed": "completed", "cancelled": "cancelled"}
DB_TO_API = {value: key for key, value in API_TO_DB.items()}
ACTIVE = ("candidate", "assigned", "completed")
TRANSITIONS = {
    "candidate": {"assigned", "cancelled"},
    "assigned": {"completed", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class ReplacementError(ValueError): pass


def _now(): return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _employee(conn, employee_id):
    row=conn.execute("SELECT * FROM employees WHERE id=?",(employee_id,)).fetchone()
    if row is None: raise ReplacementError("직원을 찾을 수 없습니다.")
    return row


def _audit(conn, action, assignment_id, actor, before, after, reason=None):
    conn.execute("""INSERT INTO audit_log(actor_type,actor_id,action,entity_type,entity_id,before_json,after_json,reason)
                    VALUES('user',?,?,'replacement_assignments',?,?,?,?)""",
                 (actor,action,assignment_id,json.dumps(before,ensure_ascii=False,sort_keys=True) if before else None,json.dumps(after,ensure_ascii=False,sort_keys=True) if after else None,reason))


def _validate_employee(employee, start_date, end_date):
    if employee["status"] != "active": raise ReplacementError("비재직 직원은 대체근무자로 배정할 수 없습니다.")
    if start_date < employee["hire_date"] or (employee["end_date"] and end_date > employee["end_date"]):
        raise ReplacementError("대체근무 기간이 직원의 재직기간을 벗어납니다.")


def _validate_absent(employee, start_date, end_date):
    if start_date < employee["hire_date"] or (employee["end_date"] and end_date > employee["end_date"]):
        raise ReplacementError("absent employee is outside the employment period")


def _validate_link(conn, leave_request_id, absent_employee_id, start_date, end_date):
    if leave_request_id is None:
        return
    linked=conn.execute("SELECT * FROM leave_requests WHERE id=?",(leave_request_id,)).fetchone()
    if linked is None:
        raise ReplacementError("linked leave request was not found")
    if absent_employee_id is None or linked["employee_id"] != absent_employee_id:
        raise ReplacementError("linked leave must belong to the absent employee")
    if linked["start_date"] > start_date or linked["end_date"] < end_date:
        raise ReplacementError("replacement period must be covered by the linked leave")


def _assert_available(conn, employee_id, start_date, end_date, exclude_id=None):
    row=conn.execute("""SELECT id FROM replacement_assignments
                        WHERE substitute_employee_id=? AND status IN ('candidate','assigned','completed')
                          AND COALESCE(start_date,work_date)<=? AND COALESCE(end_date,work_date)>=?
                          AND (? IS NULL OR id!=?) LIMIT 1""",
                     (employee_id,end_date,start_date,exclude_id,exclude_id)).fetchone()
    if row: raise ReplacementError("대체근무자가 같은 기간에 이미 배정되어 있습니다.")


def serialize(row):
    return {"id":row["id"],"absentEmployeeId":row["absent_employee_id"],"absent":row["absent_name"] if "absent_name" in row.keys() else None,
            "replacementEmployeeId":row["substitute_employee_id"],"replacement":row["substitute_name"] if "substitute_name" in row.keys() else None,
            "leaveRequestId":row["leave_request_id"],"startDate":row["start_date"] or row["work_date"],"endDate":row["end_date"] or row["work_date"],
            "zone":row["zone"],"shift":row["shift"],"status":DB_TO_API.get(row["status"],row["status"]),"note":row["note"],
            "checklist":{"keyReceived":bool(row["key_received"]),"uniformReady":bool(row["uniform_ready"]),"orientationDone":bool(row["orientation_done"])},
            "createdAt":row["created_at"],"updatedAt":row["updated_at"]}


def _get(conn, assignment_id):
    row=conn.execute("SELECT * FROM replacement_assignments WHERE id=?",(assignment_id,)).fetchone()
    if row is None: raise ReplacementError("대체근무 기록을 찾을 수 없습니다.")
    return row


def list_assignments(conn, month_start=None, month_end=None):
    where = """WHERE COALESCE(r.start_date,r.work_date)<=?
                 AND COALESCE(r.end_date,r.work_date)>=?""" if month_start and month_end else ""
    params = (month_end, month_start) if where else ()
    rows=conn.execute(f"""SELECT r.*,a.name absent_name,s.name substitute_name FROM replacement_assignments r
                         LEFT JOIN employees a ON a.id=r.absent_employee_id LEFT JOIN employees s ON s.id=r.substitute_employee_id
                         {where} ORDER BY COALESCE(r.start_date,r.work_date),r.id""",params).fetchall()
    return [serialize(r) for r in rows]


def create_assignment(conn, *, absent_employee_id, replacement_employee_id, start_date, end_date,
                      zone, shift="day", leave_request_id=None, note=None, status="planned", actor="operator"):
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,start_date,end_date)
    except MonthCloseError as exc: raise ReplacementError(str(exc)) from exc
    if end_date < start_date: raise ReplacementError("종료일은 시작일보다 빠를 수 없습니다.")
    if absent_employee_id == replacement_employee_id: raise ReplacementError("결원 직원과 대체근무자는 같을 수 없습니다.")
    substitute=_employee(conn,replacement_employee_id); _validate_employee(substitute,start_date,end_date)
    if absent_employee_id is not None: _validate_absent(_employee(conn,absent_employee_id),start_date,end_date)
    if status not in API_TO_DB: raise ReplacementError("대체근무 상태가 올바르지 않습니다.")
    if status != "planned":
        raise ReplacementError("new replacement assignments must start as planned")
    _validate_link(conn,leave_request_id,absent_employee_id,start_date,end_date)
    _assert_available(conn,replacement_employee_id,start_date,end_date)
    cursor=conn.execute("""INSERT INTO replacement_assignments
        (work_date,start_date,end_date,shift,zone,absent_employee_id,substitute_employee_id,leave_request_id,status,note,assigned_by,assigned_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (start_date,start_date,end_date,shift,zone,absent_employee_id,replacement_employee_id,leave_request_id,API_TO_DB[status],note,actor,_now()))
    assignment_id=int(cursor.lastrowid); row=_get(conn,assignment_id)
    _audit(conn,"replacement.create",assignment_id,actor,None,dict(row),note)
    return serialize(row)


def update_assignment(conn, assignment_id, changes, *, actor="operator", reason="대체근무 변경"):
    row=_get(conn,assignment_id); before=dict(row)
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["start_date"],row["end_date"])
    except MonthCloseError as exc: raise ReplacementError(str(exc)) from exc
    if row["status"] in {"completed","cancelled"}:
        raise ReplacementError("completed or cancelled assignments cannot be changed")
    if "status" in changes:
        raise ReplacementError("use the dedicated status action")
    allowed={"absentEmployeeId":"absent_employee_id","replacementEmployeeId":"substitute_employee_id","startDate":"start_date","endDate":"end_date","zone":"zone","shift":"shift","note":"note"}
    values=dict(row)
    for key,column in allowed.items():
        if key in changes: values[column]=API_TO_DB.get(changes[key],changes[key]) if key=="status" else changes[key]
    start,end=values["start_date"] or values["work_date"],values["end_date"] or values["work_date"]
    try: assert_range_open(conn,start,end)
    except MonthCloseError as exc: raise ReplacementError(str(exc)) from exc
    if end<start: raise ReplacementError("종료일은 시작일보다 빠를 수 없습니다.")
    if values["absent_employee_id"] is not None:
        _validate_absent(_employee(conn,values["absent_employee_id"]),start,end)
    substitute=_employee(conn,values["substitute_employee_id"]); _validate_employee(substitute,start,end)
    if values["absent_employee_id"]==values["substitute_employee_id"]:
        raise ReplacementError("absent and replacement employees must differ")
    _validate_link(conn,values["leave_request_id"],values["absent_employee_id"],start,end)
    _assert_available(conn,values["substitute_employee_id"],start,end,assignment_id)
    assignments=[]; params=[]
    for key,column in allowed.items():
        if key in changes:
            assignments.append(column+"=?"); params.append(values[column])
    if not assignments: raise ReplacementError("변경할 내용이 없습니다.")
    assignments.append("work_date=?"); params.append(start); assignments.append("updated_at=?"); params.append(_now()); params.append(assignment_id)
    conn.execute("UPDATE replacement_assignments SET "+",".join(assignments)+" WHERE id=?",params)
    after=dict(_get(conn,assignment_id)); _audit(conn,"replacement.update",assignment_id,actor,before,after,reason)
    return serialize(_get(conn,assignment_id))


def patch_checklist(conn, assignment_id, changes, *, actor="operator"):
    row=_get(conn,assignment_id); before=dict(row)
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["start_date"],row["end_date"])
    except MonthCloseError as exc: raise ReplacementError(str(exc)) from exc
    if row["status"] in {"completed","cancelled"}:
        raise ReplacementError("completed or cancelled assignments cannot be changed")
    mapping={"keyReceived":"key_received","uniformReady":"uniform_ready","orientationDone":"orientation_done"}
    assignments=[]; params=[]
    for key,column in mapping.items():
        if key in changes:
            assignments.append(column+"=?"); params.append(int(bool(changes[key])))
    if not assignments: raise ReplacementError("변경할 체크 항목이 없습니다.")
    assignments.append("updated_at=?"); params.append(_now()); params.append(assignment_id)
    conn.execute("UPDATE replacement_assignments SET "+",".join(assignments)+" WHERE id=?",params)
    after=dict(_get(conn,assignment_id)); _audit(conn,"replacement.checklist",assignment_id,actor,before,after,"체크리스트 변경")
    return serialize(_get(conn,assignment_id))


def set_status(conn, assignment_id, status, *, actor="operator", reason=None):
    if status not in API_TO_DB: raise ReplacementError("대체근무 상태가 올바르지 않습니다.")
    row=_get(conn,assignment_id); before=dict(row); now=_now()
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["start_date"],row["end_date"])
    except MonthCloseError as exc: raise ReplacementError(str(exc)) from exc
    target=API_TO_DB[status]
    if target not in TRANSITIONS.get(row["status"],set()):
        raise ReplacementError("this replacement status transition is not allowed")
    fields="status=?,updated_at=?"; params=[API_TO_DB[status],now]
    if status=="completed": fields+=",completed_at=?"; params.append(now)
    if status=="cancelled": fields+=",cancelled_at=?"; params.append(now)
    params.append(assignment_id); conn.execute("UPDATE replacement_assignments SET "+fields+" WHERE id=?",params)
    after=dict(_get(conn,assignment_id)); _audit(conn,"replacement."+status,assignment_id,actor,before,after,reason)
    return serialize(_get(conn,assignment_id))
