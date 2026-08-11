"""Read API for the operations console.

Phase 2 is read-only on purpose. The attendance correction write path exists as
a service (`app/services/attendance.py`) with its guarantees pinned by tests,
but no mutation endpoint is exposed until the UI actually needs attendance
editing.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from app import config, db
from app.schemas.api import (
    AttendanceDetail,
    Bootstrap,
    DocumentRow,
    LeaveCase,
    NoteRow,
    ReplacementRow,
)
from app.services import health as health_service
from app.services import ops

router = APIRouter(prefix="/api/v1", tags=["operations"])


def _connect():
    if not config.DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="database not initialised; run `python -m app.seed`",
        )
    return db.connect(config.DB_PATH, read_only=True)


def _week_start_and_today(conn) -> tuple[str, str]:
    """A demo-seeded database pins its week; a real one follows the calendar."""
    meta = ops.data_context(conn)
    if meta["data_context"] == "demo" and meta["demo_week_start"]:
        return meta["demo_week_start"], meta["demo_today"] or meta["demo_week_start"]
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat(), today.isoformat()


# exclude_none makes the payload structurally identical to the generated demo
# snapshot: absent means absent in both, so the frontend has one shape to render.
@router.get("/bootstrap", response_model=Bootstrap, response_model_exclude_none=True)
def get_bootstrap(
    start: str | None = Query(default=None, description="ISO date of the week's Monday"),
) -> Bootstrap:
    """Everything the operations views need, in the demo snapshot's shape."""
    conn = _connect()
    try:
        meta = ops.data_context(conn)
        week_start, today = _week_start_and_today(conn)
        if start:
            week_start = start
        view = ops.week_view(conn, week_start, today)
        year, month = int(week_start[:4]), int(week_start[5:7])
        fingerprint = health_service.fingerprint_status(conn)
        return Bootstrap(
            mode="operational",
            dataContext=meta["data_context"] or "unknown",
            weekStart=week_start,
            today=today,
            days=view["days"],
            employees=view["employees"],
            monthStats=ops.month_stats(conn, year, month),
            fingerprint={
                "lastImportAt": fingerprint["last_import_at"],
                "isStale": fingerprint["is_stale"],
            },
        )
    finally:
        conn.close()


@router.get("/employees")
def list_employees() -> list[dict]:
    conn = _connect()
    try:
        return [
            {
                "code": row["employee_code"],
                "name": row["name"],
                "zone": row["zone"],
                "hire": row["hire_date"],
                "end": row["end_date"],
                "slot": row["slot"],
                "leave": row["leave_left"],
                "status": row["status"],
            }
            for row in ops.employees(conn)
        ]
    finally:
        conn.close()


@router.get("/employees/{code}")
def get_employee(code: str) -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM employees WHERE employee_code = ?", (code,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no employee {code}")
        week_start, today = _week_start_and_today(conn)
        view = ops.week_view(conn, week_start, today)
        person = next((p for p in view["employees"] if p["name"] == row["name"]), None)
        return {"code": code, "profile": person, "days": view["days"]}
    finally:
        conn.close()


@router.get("/attendance", response_model=AttendanceDetail)
def get_attendance(
    employee: str = Query(description="employee code"),
    work_date: str = Query(alias="date"),
) -> AttendanceDetail:
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT a.*, e.name FROM attendance_days a
              JOIN employees e ON e.id = a.employee_id
             WHERE e.employee_code = ? AND a.work_date = ?
            """,
            (employee, work_date),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"no attendance record for {employee} on {work_date}",
            )
        punches = conn.execute(
            """
            SELECT p.punch_at, p.punch_type, p.review_flag FROM punch_events p
              JOIN employees e ON e.id = p.employee_id
             WHERE e.employee_code = ? AND p.work_date = ? AND p.rolled_back_at IS NULL
             ORDER BY p.punch_at
            """,
            (employee, work_date),
        ).fetchall()
        return AttendanceDetail(
            employee=row["name"],
            workDate=row["work_date"],
            status=row["status"],
            revision=row["revision"],
            scheduledStart=row["scheduled_start"],
            scheduledEnd=row["scheduled_end"],
            reviewFlag=row["review_flag"],
            reviewNote=row["review_note"],
            punches=[dict(p) for p in punches],
        )
    finally:
        conn.close()


@router.get("/leave", response_model=list[LeaveCase])
def list_leave() -> list[LeaveCase]:
    conn = _connect()
    try:
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
                # never silently alter either period — surface it (§7 Phase 4)
                finding = "증빙 기간이 신청 기간보다 짧습니다"
            cases.append(
                LeaveCase(
                    employee=row["name"],
                    leaveType=row["leave_type"],
                    startDate=row["start_date"],
                    endDate=row["end_date"],
                    status=row["status"],
                    workingDayCount=row["working_day_count"],
                    certStartDate=row["cert_start_date"],
                    certEndDate=row["cert_end_date"],
                    finding=finding,
                )
            )
        return cases
    finally:
        conn.close()


@router.get("/replacements", response_model=list[ReplacementRow])
def list_replacements() -> list[ReplacementRow]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT r.*, a.name AS absent_name, s.name AS substitute_name
              FROM replacement_assignments r
              LEFT JOIN employees a ON a.id = r.absent_employee_id
              LEFT JOIN employees s ON s.id = r.substitute_employee_id
             ORDER BY r.work_date, r.id
            """
        ).fetchall()
        return [
            ReplacementRow(
                workDate=row["work_date"],
                shift=row["shift"],
                zone=row["zone"],
                absent=row["absent_name"],
                substitute=row["substitute_name"],
                status=row["status"],
                reason=row["reason"],
            )
            for row in rows
        ]
    finally:
        conn.close()


@router.get("/notes", response_model=list[NoteRow])
def list_notes() -> list[NoteRow]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT n.*, e.name FROM notes n
              LEFT JOIN employees e ON e.id = n.employee_id
             ORDER BY n.created_at DESC, n.id DESC
            """
        ).fetchall()
        return [
            NoteRow(
                employee=row["name"],
                workDate=row["work_date"],
                category=row["category"],
                body=row["body"],
                author=row["author"],
                createdAt=row["created_at"],
            )
            for row in rows
        ]
    finally:
        conn.close()


@router.get("/documents", response_model=list[DocumentRow])
def list_documents() -> list[DocumentRow]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT d.*, e.name FROM documents d
              LEFT JOIN employees e ON e.id = d.employee_id
             ORDER BY d.created_at DESC, d.id DESC
            """
        ).fetchall()
        return [
            DocumentRow(
                employee=row["name"],
                docType=row["doc_type"],
                title=row["title"],
                originalFilename=row["original_filename"],
                status=row["status"],
                createdAt=row["created_at"],
            )
            for row in rows
        ]
    finally:
        conn.close()
