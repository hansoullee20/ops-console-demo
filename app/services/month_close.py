"""Deterministic reconciliation and immutable monthly close snapshots."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

import xlwt

from app.services import operational_safety

RECONCILIATION_VERSION = "1"
POLICY_VERSION = "1"
BLOCKING_CODES = {
    "scheduled_no_punch", "incomplete_day", "leave_attendance_conflict",
    "sick_leave_evidence_mismatch", "partial_leave_review",
    "covered_but_zero_events", "expected_period_not_covered",
    "source_quality_drop", "mapping_review", "manual_attendance_review",
    "import_rolled_back", "before_hire_date", "after_end_date",
}


class MonthCloseError(ValueError):
    def __init__(self, message: str, blocking_items: list[dict] | None = None):
        super().__init__(message)
        self.blocking_items = blocking_items or []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def bounds(month: str) -> tuple[str, str]:
    try:
        year, number = map(int, month.split("-"))
        if not (1 <= number <= 12 and f"{year:04d}-{number:02d}" == month):
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise MonthCloseError("month must be YYYY-MM") from exc
    return f"{month}-01", f"{month}-{monthrange(year, number)[1]:02d}"


def assert_range_open(conn: sqlite3.Connection, start: str, end: str | None = None) -> None:
    last_month = end[:7] if end else "9999-12"
    row = conn.execute(
        "SELECT month_key FROM month_closes WHERE status='closed' "
        "AND month_key>=? AND month_key<=? ORDER BY month_key LIMIT 1",
        (start[:7], last_month),
    ).fetchone()
    if row:
        raise MonthCloseError(f"{row['month_key']} 마감 월입니다. 먼저 월을 다시 여십시오.")


def _item(row: sqlite3.Row) -> dict:
    return {
        "code": row["exception_code"], "scope": row["scope"],
        "employeeId": row["employee_id"], "workDate": row["work_date"],
        "exceptionIds": [row["id"]], "reason": row["summary"],
        "status": row["status"], "severity": row["severity"],
    }


def _scheduled_employee_days(conn: sqlite3.Connection, start: str, end: str) -> int:
    count = 0
    employees = conn.execute(
        "SELECT id,hire_date,end_date FROM employees WHERE hire_date<=? "
        "AND (end_date IS NULL OR end_date>=?)", (end, start)
    ).fetchall()
    cursor, finish = date.fromisoformat(start), date.fromisoformat(end)
    while cursor <= finish:
        iso = cursor.isoformat()
        for employee in employees:
            if employee["hire_date"] <= iso and (not employee["end_date"] or iso <= employee["end_date"]):
                count += int(operational_safety.resolve_schedule(conn, employee["id"], iso)["isScheduled"])
        cursor += timedelta(days=1)
    return count


def reconcile(conn: sqlite3.Connection, month: str) -> dict:
    start, end = bounds(month)
    operational_safety.reconcile(conn, start, end)
    active = conn.execute(
        "SELECT * FROM operational_exceptions WHERE status IN ('open','acknowledged') "
        "AND ((work_date BETWEEN ? AND ?) OR (work_date IS NULL AND created_at LIKE ?)) "
        "ORDER BY COALESCE(work_date,''),id", (start, end, month + "%")
    ).fetchall()
    blockers, warnings = [], []
    for row in active:
        (blockers if row["severity"] == "critical" or row["exception_code"] in BLOCKING_CODES else warnings).append(_item(row))

    for row in conn.execute(
        "SELECT id,status FROM import_runs WHERE period_start<=? AND period_end>=? "
        "AND status IN ('pending','previewed') ORDER BY id", (end, start)
    ):
        blockers.append({"code": "pending_import", "scope": "source", "employeeId": None,
                         "workDate": None, "exceptionIds": [], "recordId": row["id"],
                         "reason": "이 달에 영향을 주는 가져오기가 아직 반영되지 않았습니다.", "status": row["status"]})

    unmapped = conn.execute(
        "SELECT COUNT(*) FROM punch_events WHERE work_date BETWEEN ? AND ? "
        "AND employee_id IS NULL AND rolled_back_at IS NULL", (start, end)
    ).fetchone()[0]
    if unmapped:
        blockers.append({"code": "unmapped_punch", "scope": "source", "employeeId": None,
                         "workDate": None, "exceptionIds": [], "reason": f"직원 미연결 지문 {unmapped}건", "status": "open"})

    for row in conn.execute(
        "SELECT id,start_date,status FROM replacement_assignments "
        "WHERE start_date<=? AND end_date>=? AND status='planned' ORDER BY id", (end, start)
    ):
        blockers.append({"code": "replacement_unresolved", "scope": "replacement", "employeeId": None,
                         "workDate": row["start_date"], "exceptionIds": [], "recordId": row["id"],
                         "reason": "대체근무가 아직 확정되지 않았습니다.", "status": row["status"]})

    summary = {
        "scheduledEmployeeDays": _scheduled_employee_days(conn, start, end),
        "normalConfirmedEmployeeDays": conn.execute(
            "SELECT COUNT(*) FROM attendance_days WHERE work_date BETWEEN ? AND ? "
            "AND (status='normal' OR confirmed_at IS NOT NULL)", (start, end)).fetchone()[0],
        "leaveEmployeeDays": conn.execute(
            "SELECT COUNT(*) FROM attendance_days WHERE work_date BETWEEN ? AND ? "
            "AND status IN ('leave','half_day','sick_leave')", (start, end)).fetchone()[0],
        "reviewNeeded": len(blockers),
        "sourceQualityWarnings": sum(x["scope"] in {"source", "site"} for x in blockers + warnings),
    }
    current = conn.execute(
        "SELECT * FROM month_closes WHERE month_key=? ORDER BY revision DESC LIMIT 1", (month,)
    ).fetchone()
    return {"month": month,
            "reconciliationStatus": "closed" if current and current["status"] == "closed" else ("blocked" if blockers else "ready"),
            "summary": summary, "blockingItems": blockers, "warningItems": warnings,
            "close": dict(current) if current else None}


def _snapshot_rows(conn: sqlite3.Connection, month: str) -> list[dict]:
    start, end = bounds(month)
    specs = [
        ("attendance", "attendance_days", "work_date BETWEEN ? AND ?", (start, end)),
        ("punch", "punch_events", "work_date BETWEEN ? AND ?", (start, end)),
        ("leave", "leave_requests", "start_date<=? AND end_date>=?", (end, start)),
        ("replacement", "replacement_assignments", "start_date<=? AND end_date>=?", (end, start)),
        ("manual_adjustment", "manual_attendance_adjustments", "work_date BETWEEN ? AND ?", (start, end)),
    ]
    rows: list[dict] = []
    for kind, table, where, params in specs:
        for raw in conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY id", params):
            data = dict(raw)
            work_date = data.get("work_date") or data.get("start_date")
            rows.append({"sortKey": f"{kind}|{work_date or ''}|{data['id']:012d}",
                         "employeeId": data.get("employee_id") or data.get("absent_employee_id"),
                         "workDate": work_date, "recordType": kind, "recordId": data["id"],
                         "normalizedState": data.get("status") or data.get("review_flag") or "evidence",
                         "evidence": data})
    return sorted(rows, key=lambda row: row["sortKey"])


def _canonical(month: str, revision: int, rows: list, exceptions: list, sources: list) -> str:
    return json.dumps({"month": month, "revision": revision, "items": rows,
                       "exceptions": exceptions, "sources": sources},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def close_month(conn: sqlite3.Connection, month: str, actor: str, note: str) -> dict:
    if not actor.strip() or not note.strip():
        raise MonthCloseError("담당자와 마감 사유가 필요합니다.")
    if conn.execute("SELECT 1 FROM month_closes WHERE month_key=? AND status='closed'", (month,)).fetchone():
        raise MonthCloseError("month is already closed")
    result = reconcile(conn, month)
    if result["blockingItems"]:
        raise MonthCloseError("month has unresolved blockers", result["blockingItems"])
    revision = conn.execute("SELECT COALESCE(MAX(revision),0)+1 FROM month_closes WHERE month_key=?", (month,)).fetchone()[0]
    rows = _snapshot_rows(conn, month)
    exceptions = [dict(row) for row in conn.execute(
        "SELECT id,status,resolution_note FROM operational_exceptions WHERE work_date LIKE ? ORDER BY id", (month + "-%",))]
    start, end = bounds(month)
    sources = [{"type": "import_run", "id": row[0]} for row in conn.execute(
        "SELECT id FROM import_runs WHERE period_start<=? AND period_end>=? AND status='applied' ORDER BY id", (end, start))]
    digest = hashlib.sha256(_canonical(month, revision, rows, exceptions, sources).encode("utf-8")).hexdigest()
    close_id = conn.execute(
        "INSERT INTO month_closes(month_key,revision,status,reconciliation_version,policy_version,"
        "closed_at,closed_by,close_note,snapshot_hash) VALUES(?,?,'closed',?,?,?,?,?,?)",
        (month, revision, RECONCILIATION_VERSION, POLICY_VERSION, _now(), actor, note, digest),
    ).lastrowid
    for row in rows:
        conn.execute("INSERT INTO month_close_items(close_id,sort_key,employee_id,work_date,record_type,record_id,normalized_state,evidence_json) VALUES(?,?,?,?,?,?,?,?)",
                     (close_id, row["sortKey"], row["employeeId"], row["workDate"], row["recordType"], row["recordId"], row["normalizedState"], json.dumps(row["evidence"], ensure_ascii=False, sort_keys=True)))
    for row in exceptions:
        conn.execute("INSERT INTO month_close_exception_links(close_id,exception_id,status_at_close,resolution_note) VALUES(?,?,?,?)",
                     (close_id, row["id"], row["status"], row["resolution_note"]))
    for source in sources:
        conn.execute("INSERT INTO month_close_source_links(close_id,source_type,source_id) VALUES(?,?,?)", (close_id, source["type"], source["id"]))
    conn.execute("INSERT INTO audit_log(actor_type,actor_id,action,entity_type,entity_id,after_json,reason) VALUES('user',?,'month_close.close','month_closes',?,?,?)",
                 (actor, close_id, json.dumps({"month": month, "revision": revision, "snapshotHash": digest}), note))
    return get_close(conn, close_id)


def reopen(conn: sqlite3.Connection, month: str, actor: str, reason: str) -> dict:
    if not actor.strip() or not reason.strip():
        raise MonthCloseError("담당자와 다시 열기 사유가 필요합니다.")
    row = conn.execute("SELECT * FROM month_closes WHERE month_key=? AND status='closed'", (month,)).fetchone()
    if not row:
        raise MonthCloseError("closed month not found")
    conn.execute("UPDATE month_closes SET status='reopened',reopened_at=?,reopened_by=?,reopen_reason=? WHERE id=?",
                 (_now(), actor, reason, row["id"]))
    conn.execute("INSERT INTO audit_log(actor_type,actor_id,action,entity_type,entity_id,before_json,reason) VALUES('user',?,'month_close.reopen','month_closes',?,?,?)",
                 (actor, row["id"], json.dumps(dict(row), ensure_ascii=False, sort_keys=True), reason))
    return get_close(conn, row["id"])


def get_close(conn: sqlite3.Connection, close_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM month_closes WHERE id=?", (close_id,)).fetchone()
    return dict(row) if row else None


def latest(conn: sqlite3.Connection, month: str) -> dict | None:
    bounds(month)
    row = conn.execute("SELECT * FROM month_closes WHERE month_key=? ORDER BY revision DESC LIMIT 1", (month,)).fetchone()
    return dict(row) if row else None


def snapshot(conn: sqlite3.Connection, month: str) -> dict:
    close = latest(conn, month)
    if not close:
        raise MonthCloseError("month close not found")
    items = [dict(row) for row in conn.execute("SELECT * FROM month_close_items WHERE close_id=? ORDER BY sort_key", (close["id"],))]
    exceptions = [dict(row) for row in conn.execute("SELECT * FROM month_close_exception_links WHERE close_id=? ORDER BY exception_id", (close["id"],))]
    sources = [dict(row) for row in conn.execute("SELECT * FROM month_close_source_links WHERE close_id=? ORDER BY source_type,source_id", (close["id"],))]
    return {"close": close, "items": items, "exceptions": exceptions, "sources": sources}


def export_xls(conn: sqlite3.Connection, month: str) -> bytes:
    """Build the generic submission workbook exclusively from a close snapshot."""
    frozen = snapshot(conn, month)
    if frozen["close"]["status"] not in {"closed", "reopened"}:
        raise MonthCloseError("closed snapshot not found")
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("제출용 근태자료")
    title = xlwt.easyxf("font: bold on, height 300; align: horiz center; pattern: pattern solid, fore_colour ice_blue;")
    header = xlwt.easyxf("font: bold on, colour white; pattern: pattern solid, fore_colour dark_blue; align: horiz center;")
    sheet.write_merge(0, 0, 0, 6, f"제출용 근태자료 {month} (일반 형식)", title)
    labels = ["구분", "직원 ID", "근무일", "상태", "기록 ID", "스냅샷 개정", "스냅샷 해시"]
    for col, label in enumerate(labels): sheet.write(2, col, label, header)
    for idx, item in enumerate(frozen["items"], 3):
        values = [item["record_type"], item["employee_id"], item["work_date"], item["normalized_state"], item["record_id"], frozen["close"]["revision"], frozen["close"]["snapshot_hash"]]
        for col, value in enumerate(values): sheet.write(idx, col, "" if value is None else value)
    for col, width in enumerate((18, 12, 14, 20, 12, 14, 68)): sheet.col(col).width = width * 256
    output = io.BytesIO(); book.save(output); return output.getvalue()
