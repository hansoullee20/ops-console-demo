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

RECONCILIATION_VERSION = "2"
POLICY_VERSION = "2"
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


class MonthCloseIntegrityError(MonthCloseError):
    """Stored close material no longer matches its immutable digest/links."""


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


def _exception_ranges(conn: sqlite3.Connection, exception_id: int) -> list[tuple[str, str]]:
    """Resolve the real affected periods for dated and source/entity exceptions."""
    exception = conn.execute(
        "SELECT work_date,import_run_id,status FROM operational_exceptions WHERE id=?",
        (exception_id,),
    ).fetchone()
    if not exception:
        return []
    ranges: set[tuple[str, str]] = set()
    if exception["work_date"]:
        ranges.add((exception["work_date"], exception["work_date"]))
    import_ids = {exception["import_run_id"]} if exception["import_run_id"] else set()
    specs = {
        "leave_request": ("leave_requests", "start_date", "end_date", False),
        "leave_requests": ("leave_requests", "start_date", "end_date", False),
        "replacement_assignment": ("replacement_assignments", "start_date", "end_date", False),
        "replacement_assignments": ("replacement_assignments", "start_date", "end_date", False),
        "terminal_slot": ("terminal_slots", "effective_from", "effective_to", True),
        "terminal_slots": ("terminal_slots", "effective_from", "effective_to", True),
        "source_quality_observation": ("source_quality_observations", "COALESCE(period_start,work_date)", "COALESCE(period_end,work_date)", False),
        "source_quality_observations": ("source_quality_observations", "COALESCE(period_start,work_date)", "COALESCE(period_end,work_date)", False),
    }
    for link in conn.execute(
        "SELECT entity_type,entity_id,import_run_id FROM exception_evidence_links WHERE exception_id=?",
        (exception_id,),
    ):
        if link["import_run_id"]:
            import_ids.add(link["import_run_id"])
        if link["entity_type"] in {"import_run", "import_runs"} and link["entity_id"] is not None:
            import_ids.add(link["entity_id"])
        if link["entity_type"] in specs and link["entity_id"] is not None:
            table, start_column, end_column, open_ended = specs[link["entity_type"]]
            row = conn.execute(
                f"SELECT {start_column} AS starts,{end_column} AS ends FROM {table} WHERE id=?",
                (link["entity_id"],),
            ).fetchone()
            if row and row["starts"]:
                ranges.add((row["starts"], row["ends"] or ("9999-12-31" if open_ended else row["starts"])))
    for import_id in import_ids:
        row = conn.execute("SELECT period_start,period_end FROM import_runs WHERE id=?", (import_id,)).fetchone()
        if row and row["period_start"]:
            ranges.add((row["period_start"], row["period_end"] or row["period_start"]))
    if not ranges and exception["status"] in {"open", "acknowledged"}:
        # Never assign an undated unresolved issue by creation month alone.
        # Without authoritative scope evidence, conservatively treat it as
        # global so it cannot silently disappear from reconciliation.
        ranges.add(("0001-01-01", "9999-12-31"))
    return sorted(ranges)


def assert_exception_open(conn: sqlite3.Connection, exception_id: int) -> None:
    for start, end in _exception_ranges(conn, exception_id):
        assert_range_open(conn, start, end)


def _month_exception_rows(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    """One authoritative attribution set shared by reconciliation and snapshotting."""
    rows = conn.execute("SELECT * FROM operational_exceptions ORDER BY id").fetchall()
    return [row for row in rows if any(left <= end and right >= start for left, right in _exception_ranges(conn, row["id"]))]


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
                schedule = operational_safety.resolve_schedule(conn, employee["id"], iso)
                count += int(schedule["isAuthoritative"] and schedule["isScheduled"])
        cursor += timedelta(days=1)
    return count


def _schedule_coverage_blockers(conn: sqlite3.Connection, start: str, end: str) -> list[dict]:
    """Report employment dates lacking authoritative employee schedule evidence.

    These are operational completeness blockers, never attendance conclusions.
    A date is covered by an active date override or an active date-scoped work
    schedule, including schedule weekdays that explicitly resolve to non-work.
    Site calendar and weekday fallback do not establish employee coverage.
    """
    blockers: list[dict] = []
    employees = conn.execute(
        "SELECT id,hire_date,end_date FROM employees WHERE hire_date<=? "
        "AND (end_date IS NULL OR end_date>=?) ORDER BY id", (end, start)
    ).fetchall()
    for employee in employees:
        first = max(date.fromisoformat(start), date.fromisoformat(employee["hire_date"]))
        last = min(date.fromisoformat(end), date.fromisoformat(employee["end_date"] or end))
        missing: list[date] = []
        cursor = first
        while cursor <= last:
            resolved = operational_safety.resolve_schedule(conn, employee["id"], cursor.isoformat())
            if not resolved["isAuthoritative"]:
                missing.append(cursor)
            cursor += timedelta(days=1)
        if not missing:
            continue
        ranges: list[tuple[date, date]] = []
        range_start = range_end = missing[0]
        for uncovered in missing[1:]:
            if uncovered == range_end + timedelta(days=1):
                range_end = uncovered
            else:
                ranges.append((range_start, range_end))
                range_start = range_end = uncovered
        ranges.append((range_start, range_end))
        for range_start, range_end in ranges:
            blockers.append({
                "code": "schedule_coverage_incomplete", "scope": "schedule",
                "employeeId": employee["id"], "workDate": range_start.isoformat(),
                "periodEnd": range_end.isoformat(), "exceptionIds": [],
                "reason": "이 직원·기간의 근무예정일을 판단할 권위 있는 개인 일정 근거가 없어 월 근태 완전성을 검증할 수 없습니다.",
                "status": "open", "severity": "review",
            })
    return blockers


def reconcile(conn: sqlite3.Connection, month: str) -> dict:
    start, end = bounds(month)
    current = conn.execute(
        "SELECT * FROM month_closes WHERE month_key=? ORDER BY revision DESC LIMIT 1", (month,)
    ).fetchone()
    # A closed month is an immutable historical result. GET reconciliation is
    # read-only until an explicit reopen makes live re-evaluation permissible.
    if not current or current["status"] != "closed":
        operational_safety.reconcile(conn, start, end)
    active = [row for row in _month_exception_rows(conn, start, end)
              if row["status"] in {"open", "acknowledged"}]
    blockers, warnings = [], []
    for row in active:
        (blockers if row["severity"] in {"critical", "review"} or row["exception_code"] in BLOCKING_CODES else warnings).append(_item(row))

    blockers.extend(_schedule_coverage_blockers(conn, start, end))

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
        "WHERE start_date<=? AND end_date>=? AND status='candidate' ORDER BY id", (end, start)
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


def _canonical(month: str, revision: int, rows: list, exceptions: list, sources: list,
               event_ids: list[int] | None = None, evidence_ids: list[int] | None = None,
               supersedes_close_id: int | None = None, *, version: str = "2") -> str:
    value = {"month": month, "revision": revision, "items": rows,
             "exceptions": exceptions, "sources": sources}
    if version != "1":
        value.update({"exceptionEventIds": event_ids or [],
                      "exceptionEvidenceLinkIds": evidence_ids or [],
                      "supersedesCloseId": supersedes_close_id})
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def close_month(conn: sqlite3.Connection, month: str, actor: str, note: str) -> dict:
    if not actor.strip() or not note.strip():
        raise MonthCloseError("담당자와 마감 사유가 필요합니다.")
    if conn.execute("SELECT 1 FROM month_closes WHERE month_key=? AND status='closed'", (month,)).fetchone():
        raise MonthCloseError("month is already closed")
    result = reconcile(conn, month)
    if result["blockingItems"]:
        raise MonthCloseError("month has unresolved blockers", result["blockingItems"])
    previous = conn.execute(
        "SELECT id,revision FROM month_closes WHERE month_key=? ORDER BY revision DESC LIMIT 1", (month,)
    ).fetchone()
    revision = (previous["revision"] + 1) if previous else 1
    supersedes_close_id = previous["id"] if previous else None
    rows = _snapshot_rows(conn, month)
    start, end = bounds(month)
    exception_rows = _month_exception_rows(conn, start, end)
    exceptions = [{"id": row["id"], "status": row["status"],
                   "resolution_note": row["resolution_note"]} for row in exception_rows]
    exception_ids = [row["id"] for row in exception_rows]
    event_ids: list[int] = []
    evidence_ids: list[int] = []
    if exception_ids:
        placeholders = ",".join("?" for _ in exception_ids)
        event_ids = [row[0] for row in conn.execute(
            f"SELECT id FROM exception_events WHERE exception_id IN ({placeholders}) ORDER BY id", exception_ids)]
        evidence_ids = [row[0] for row in conn.execute(
            f"SELECT id FROM exception_evidence_links WHERE exception_id IN ({placeholders}) ORDER BY id", exception_ids)]
    sources = [{"type": "import_run", "id": row[0]} for row in conn.execute(
        "SELECT id FROM import_runs WHERE period_start<=? AND period_end>=? AND status='applied' ORDER BY id", (end, start))]
    digest = hashlib.sha256(_canonical(
        month, revision, rows, exceptions, sources, event_ids, evidence_ids,
        supersedes_close_id,
    ).encode("utf-8")).hexdigest()
    close_id = conn.execute(
        "INSERT INTO month_closes(month_key,revision,status,reconciliation_version,policy_version,"
        "closed_at,closed_by,close_note,snapshot_hash,supersedes_close_id) "
        "VALUES(?,?,'closed',?,?,?,?,?,?,?)",
        (month, revision, RECONCILIATION_VERSION, POLICY_VERSION, _now(), actor, note,
         digest, supersedes_close_id),
    ).lastrowid
    for row in rows:
        conn.execute("INSERT INTO month_close_items(close_id,sort_key,employee_id,work_date,record_type,record_id,normalized_state,evidence_json) VALUES(?,?,?,?,?,?,?,?)",
                     (close_id, row["sortKey"], row["employeeId"], row["workDate"], row["recordType"], row["recordId"], row["normalizedState"], json.dumps(row["evidence"], ensure_ascii=False, sort_keys=True)))
    for row in exceptions:
        conn.execute("INSERT INTO month_close_exception_links(close_id,exception_id,status_at_close,resolution_note) VALUES(?,?,?,?)",
                     (close_id, row["id"], row["status"], row["resolution_note"]))
    for source in sources:
        conn.execute("INSERT INTO month_close_source_links(close_id,source_type,source_id) VALUES(?,?,?)", (close_id, source["type"], source["id"]))
    for event_id in event_ids:
        conn.execute("INSERT INTO month_close_exception_event_links(close_id,exception_event_id) VALUES(?,?)",
                     (close_id, event_id))
    for evidence_id in evidence_ids:
        conn.execute("INSERT INTO month_close_exception_evidence_links(close_id,exception_evidence_link_id) VALUES(?,?)",
                     (close_id, evidence_id))
    conn.execute("INSERT INTO audit_log(actor_type,actor_id,action,entity_type,entity_id,after_json,reason) VALUES('user',?,'month_close.close','month_closes',?,?,?)",
                 (actor, close_id, json.dumps({"month": month, "revision": revision,
                                              "snapshotHash": digest,
                                              "supersedesCloseId": supersedes_close_id}), note))
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


def list_revisions(conn: sqlite3.Connection, month: str) -> list[dict]:
    bounds(month)
    return [dict(row) for row in conn.execute(
        "SELECT * FROM month_closes WHERE month_key=? ORDER BY revision", (month,)
    )]


def _select_close(conn: sqlite3.Connection, month: str, *, close_id: int | None = None,
                  revision: int | None = None) -> dict | None:
    bounds(month)
    if close_id is not None:
        row = conn.execute("SELECT * FROM month_closes WHERE month_key=? AND id=?", (month, close_id)).fetchone()
    elif revision is not None:
        row = conn.execute("SELECT * FROM month_closes WHERE month_key=? AND revision=?", (month, revision)).fetchone()
    else:
        row = conn.execute("SELECT * FROM month_closes WHERE month_key=? ORDER BY revision DESC LIMIT 1", (month,)).fetchone()
    return dict(row) if row else None


def snapshot(conn: sqlite3.Connection, month: str, *, close_id: int | None = None,
             revision: int | None = None) -> dict:
    close = _select_close(conn, month, close_id=close_id, revision=revision)
    if not close:
        raise MonthCloseError("month close not found")
    items = [dict(row) for row in conn.execute("SELECT * FROM month_close_items WHERE close_id=? ORDER BY sort_key", (close["id"],))]
    exceptions = [dict(row) for row in conn.execute("SELECT * FROM month_close_exception_links WHERE close_id=? ORDER BY exception_id", (close["id"],))]
    sources = [dict(row) for row in conn.execute("SELECT * FROM month_close_source_links WHERE close_id=? ORDER BY source_type,source_id", (close["id"],))]
    event_ids = [row[0] for row in conn.execute(
        "SELECT exception_event_id FROM month_close_exception_event_links WHERE close_id=? ORDER BY exception_event_id",
        (close["id"],))]
    evidence_ids = [row[0] for row in conn.execute(
        "SELECT exception_evidence_link_id FROM month_close_exception_evidence_links WHERE close_id=? ORDER BY exception_evidence_link_id",
        (close["id"],))]
    for source in sources:
        if source["source_type"] != "import_run" or not conn.execute(
            "SELECT 1 FROM import_runs WHERE id=?", (source["source_id"],)
        ).fetchone():
            raise MonthCloseIntegrityError("month close source link is invalid")
    canonical_items = [{"sortKey": row["sort_key"], "employeeId": row["employee_id"],
                        "workDate": row["work_date"], "recordType": row["record_type"],
                        "recordId": row["record_id"], "normalizedState": row["normalized_state"],
                        "evidence": json.loads(row["evidence_json"])} for row in items]
    canonical_exceptions = [{"id": row["exception_id"], "status": row["status_at_close"],
                             "resolution_note": row["resolution_note"]} for row in exceptions]
    canonical_sources = [{"type": row["source_type"], "id": row["source_id"]} for row in sources]
    version = close["reconciliation_version"]
    canonical = _canonical(close["month_key"], close["revision"], canonical_items,
                           canonical_exceptions, canonical_sources, event_ids, evidence_ids,
                           close.get("supersedes_close_id"), version=version)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if digest != close["snapshot_hash"]:
        raise MonthCloseIntegrityError("month close snapshot hash mismatch")
    return {"close": close, "items": items, "exceptions": exceptions, "sources": sources,
            "exceptionEventIds": event_ids, "exceptionEvidenceLinkIds": evidence_ids}


def export_xls(conn: sqlite3.Connection, month: str, *, close_id: int | None = None,
               revision: int | None = None) -> bytes:
    """Build the generic submission workbook exclusively from a close snapshot."""
    explicit_revision = close_id is not None or revision is not None
    frozen = snapshot(conn, month, close_id=close_id, revision=revision)
    if frozen["close"]["status"] != "closed" and not explicit_revision:
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
