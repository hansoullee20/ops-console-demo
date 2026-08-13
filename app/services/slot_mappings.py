"""Operational management of date-scoped fingerprint terminal slots."""
from __future__ import annotations

import json
import sqlite3
from datetime import date


class MappingError(ValueError):
    pass


def list_mappings(conn: sqlite3.Connection) -> dict:
    employees = [
        dict(row)
        for row in conn.execute(
            "SELECT id, employee_code, name, status, hire_date, end_date "
            "FROM employees ORDER BY name, id"
        )
    ]
    mappings = [
        dict(row)
        for row in conn.execute(
            """SELECT t.id, t.terminal_id, t.slot_code, t.employee_id,
                      t.effective_from, t.effective_to, t.status,
                      e.name AS employee_name
                 FROM terminal_slots t
                 LEFT JOIN employees e ON e.id = t.employee_id
                ORDER BY t.slot_code, t.effective_from, t.id"""
        )
    ]
    today = date.today().isoformat()
    for row in mappings:
        if row["status"] == "retired":
            row["range_status"] = "cancelled"
        elif row["effective_from"] > today:
            row["range_status"] = "future"
        elif row["effective_to"] and row["effective_to"] < today:
            row["range_status"] = "expired"
        else:
            row["range_status"] = "active"
    discovered = {
        row[0]
        for row in conn.execute("SELECT DISTINCT terminal_slot_code FROM punch_events")
    }
    discovered.update(
        row[0] for row in conn.execute("SELECT DISTINCT slot_code FROM terminal_slots")
    )
    return {"slots": sorted(discovered), "mappings": mappings, "employees": employees}


def _audit(conn: sqlite3.Connection, action: str, mapping_id: int, before: dict | None,
           after: dict | None, reason: str | None, actor_id: str) -> None:
    conn.execute(
        """INSERT INTO audit_log
               (actor_type, actor_id, action, entity_type, entity_id,
                before_json, after_json, reason)
           VALUES ('user', ?, ?, 'terminal_slots', ?, ?, ?, ?)""",
        (
            actor_id,
            action,
            mapping_id,
            json.dumps(before, ensure_ascii=False) if before else None,
            json.dumps(after, ensure_ascii=False) if after else None,
            reason,
        ),
    )


def create_mapping(
    conn: sqlite3.Connection,
    *,
    slot_code: str,
    employee_id: int,
    effective_from: str,
    effective_to: str | None = None,
    terminal_id: str = "default",
    actor_id: str = "operator",
) -> int:
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,effective_from,effective_to)
    except MonthCloseError as exc: raise MappingError(str(exc)) from exc
    slot_code = slot_code.strip()
    effective_to = effective_to or None
    if not slot_code or not effective_from:
        raise MappingError("슬롯과 적용 시작일이 필요합니다.")
    if effective_to and effective_to < effective_from:
        raise MappingError("적용 종료일은 시작일보다 빠를 수 없습니다.")
    if conn.execute("SELECT 1 FROM employees WHERE id = ?", (employee_id,)).fetchone() is None:
        raise MappingError("선택한 직원을 찾을 수 없습니다.")
    overlap = conn.execute(
        """SELECT id FROM terminal_slots
            WHERE terminal_id = ? AND slot_code = ? AND status != 'retired'
              AND COALESCE(effective_to, '9999-12-31') >= ?
              AND COALESCE(?, '9999-12-31') >= effective_from
            LIMIT 1""",
        (terminal_id, slot_code, effective_from, effective_to),
    ).fetchone()
    if overlap:
        raise MappingError("이 슬롯에는 선택한 기간과 겹치는 기존 연결이 있습니다.")
    cursor = conn.execute(
        """INSERT INTO terminal_slots
               (terminal_id, slot_code, employee_id, effective_from, effective_to, status)
           VALUES (?, ?, ?, ?, ?, 'mapped')""",
        (terminal_id, slot_code, employee_id, effective_from, effective_to),
    )
    mapping_id = int(cursor.lastrowid)
    after = dict(conn.execute("SELECT * FROM terminal_slots WHERE id = ?", (mapping_id,)).fetchone())
    _audit(conn, "terminal_slot.create", mapping_id, None, after, None, actor_id)
    return mapping_id


def close_mapping(
    conn: sqlite3.Connection, mapping_id: int, effective_to: str,
    *, actor_id: str = "operator",
) -> None:
    row = conn.execute("SELECT * FROM terminal_slots WHERE id = ?", (mapping_id,)).fetchone()
    from app.services.month_close import MonthCloseError,assert_range_open
    if row:
        try: assert_range_open(conn,row["effective_from"],effective_to)
        except MonthCloseError as exc: raise MappingError(str(exc)) from exc
    if row is None or row["status"] == "retired":
        raise MappingError("연결 이력을 찾을 수 없습니다.")
    if row["effective_to"] is not None:
        raise MappingError("이미 종료일이 있는 연결입니다.")
    if effective_to < row["effective_from"]:
        raise MappingError("종료일은 시작일보다 빠를 수 없습니다.")
    excluded_active_punch = conn.execute(
        """SELECT 1 FROM punch_events
            WHERE terminal_id = ? AND terminal_slot_code = ? AND employee_id = ?
              AND work_date >= ? AND work_date > ?
              AND rolled_back_at IS NULL
            LIMIT 1""",
        (
            row["terminal_id"], row["slot_code"], row["employee_id"],
            row["effective_from"], effective_to,
        ),
    ).fetchone()
    if excluded_active_punch:
        raise MappingError(
            "이미 반영된 지문이 이 연결을 사용합니다. 먼저 해당 가져오기를 되돌리십시오."
        )
    before = dict(row)
    conn.execute("UPDATE terminal_slots SET effective_to = ? WHERE id = ?", (effective_to, mapping_id))
    after = dict(conn.execute("SELECT * FROM terminal_slots WHERE id = ?", (mapping_id,)).fetchone())
    _audit(conn, "terminal_slot.close", mapping_id, before, after, "연결 종료일 지정", actor_id)


def cancel_mapping(
    conn: sqlite3.Connection, mapping_id: int, reason: str,
    *, actor_id: str = "operator",
) -> None:
    """Cancel a mistaken mapping only while no active imported punch relies on it."""
    if len(reason.strip()) < 2:
        raise Mappi…13728 tokens truncated…atus']}'; only an applied run can be rolled back"
            )
        from app.services.month_close import MonthCloseError, assert_range_open
        try: assert_range_open(conn, run["period_start"], run["period_end"])
        except MonthCloseError as exc: raise ImportError_(str(exc)) from exc

        safe, conflicts = _rollback_conflicts(conn, import_run_id, run["finished_at"])

        conn.execute("BEGIN")
        # By active_import_run_id, not import_run_id: an event first imported by
        # run 1 and reactivated by run 3 is run 3's to undo. import_run_id is
        # immutable provenance and answers a different question.
        marked = conn.execute(
            "UPDATE punch_events SET rolled_back_at = ?, rolled_back_reason = ? "
            " WHERE active_import_run_id = ? AND rolled_back_at IS NULL",
            (_now(), reason, import_run_id),
        ).rowcount
        redone = derive_attendance(
            conn, safe, import_run_id=import_run_id, owned=set(safe)
        )

        conn.execute(
            "UPDATE import_runs SET status = 'rolled_back', rolled_back_at = ?, "
            "       findings_json = ? WHERE id = ?",
            (_now(),
             json.dumps({"rollbackConflicts": [c.as_dict() for c in conflicts]},
                        ensure_ascii=False),
             import_run_id),
        )
        conn.execute(
            """
            INSERT INTO audit_log (actor_type, actor_id, action, entity_type, entity_id,
                                   after_json, reason)
            VALUES ('import', ?, 'import.rollback', 'import_runs', ?, ?, ?)
            """,
            (actor_id, import_run_id,
             json.dumps({"punchesMarked": marked, "attendanceRedone": redone,
                         "conflicts": len(conflicts)}, ensure_ascii=False),
             reason),
        )
        conn.commit()
        return {
            "importRunId": import_run_id,
            "punchesMarkedRolledBack": marked,
            "attendanceRecomputed": redone,
            "punchesDeleted": 0,
            "conflicts": [c.as_dict() for c in conflicts],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# read models
#
# The API renders these; nothing re-queries import_runs on its own. Phase 2
# established the pattern with app/services/ops.py, where the API and the demo
# snapshot exporter share one set of read models so the two renderings cannot
# drift. The same reason applies to any later interface: a second caller that
# writes its own SQL is a second definition of what an import "is".
# ---------------------------------------------------------------------------
def import_history(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """
        SELECT r.id, r.source_filename, r.status, r.period_start, r.period_end,
               r.punch_event_count, r.started_at, r.finished_at, r.rolled_back_at,
               r.error_message,
               (SELECT COUNT(*) FROM import_run_days d WHERE d.import_run_id = r.id)
                   AS covered_days
          FROM import_runs r
         WHERE r.source_kind = 'fingerprint_xls'
         ORDER BY r.id DESC LIMIT ?
        """,
        (max(1, min(limit, 200)),),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "sourceFilename": row["source_filename"],
            "status": row["status"],
            "periodStart": row["period_start"],
            "periodEnd": row["period_end"],
            "punchEventCount": row["punch_event_count"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "rolledBackAt": row["rolled_back_at"],
            "errorMessage": row["error_message"],
            "coveredDays": row["covered_days"],
        }
        for row in rows
    ]


def import_run_detail(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM import_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    days = conn.execute(
        "SELECT work_date, coverage_status, raw_punch_count FROM import_run_days "
        " WHERE import_run_id = ? ORDER BY work_date",
        (run_id,),
    ).fetchall()
    findings: list[dict] = []
    if row["findings_json"]:
        try:
            findings = json.loads(row["findings_json"]).get("findings", [])
        except ValueError:  # pragma: no cover - defensive
            findings = []
    return {
        "id": row["id"],
        "sourceFilename": row["source_filename"],
        "status": row["status"],
        "periodStart": row["period_start"],
        "periodEnd": row["period_end"],
        "punchEventCount": row["punch_event_count"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "rolledBackAt": row["rolled_back_at"],
        "errorMessage": row["error_message"],
        "coveredDays": len(days),
        "sourceSha256": row["source_sha256"],
        "findings": findings,
        # Coverage facts, kept apart from any attendance verdict: a
        # reported_zero day is what the file said, not an absence.
        "days": [
            {
                "workDate": day["work_date"],
                "coverage": day["coverage_status"],
                "punches": day["raw_punch_count"],
            }
            for day in days
        ],
    }


def stored_preview(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """The preview snapshot as the operator would have seen it.

    Returns None when the run has none — a run that failed to parse, or one
    already applied. Applying never trusts this: it re-reads the preserved file
    and recomputes against the current slot mapping.
    """
    row = conn.execute(
        "SELECT preview_json FROM import_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None or not row["preview_json"]:
        return None
    return json.loads(row["preview_json"])


def preserved_source(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """Where the untouched original is kept.

    The path, not the bytes: the file stays on the work PC's disk and is never
    served to a caller.
    """
    row = conn.execute(
        "SELECT stored_source_path, source_filename, source_sha256 "
        "  FROM import_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    stored = Path(row["stored_source_path"] or "")
    return {
        "sourceFilename": row["source_filename"],
        "storedPath": str(stored),
        "exists": stored.is_file(),
        "sha256": row["source_sha256"],
    }


def pending_imports(conn: sqlite3.Connection) -> list[dict]:
    """Previewed imports waiting for somebody to confirm or discard them."""
    rows = conn.execute(
        """
        SELECT id, source_filename, period_start, period_end, started_at,
               discovered_by, preview_json
          FROM import_runs
         WHERE status = 'previewed' AND source_kind = 'fingerprint_xls'
         ORDER BY id DESC
        """
    ).fetchall()
    out = []
    for row in rows:
        new_punches = None
        state = "검토 필요"
        if row["preview_json"]:
            try:
                saved = json.loads(row["preview_json"])
                new_punches = saved.get("newPunches")
                if any(s.get("status") == "unmapped" and s.get("punchCount", 0) > 0 for s in saved.get("slots", [])):
                    state = "직원 연결 필요"
                elif saved.get("canApply"):
                    state = "반영 가능"
                elif not new_punches and not saved.get("reactivatablePunches"):
                    state = "이미 가져온 파일"
                else:
                    state = "차단됨"
            except ValueError:  # pragma: no cover - defensive
                new_punches = None
        out.append({
            "importRunId": row["id"],
            "sourceFilename": row["source_filename"],
            "periodStart": row["period_start"],
            "periodEnd": row["period_end"],
            "startedAt": row["started_at"],
            "discoveredBy": row["discovered_by"],
            "newPunches": new_punches,
            "state": state,
        })
    return out


def last_applied_import(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT id, source_filename, period_start, period_end, finished_at, punch_event_count "
        "  FROM import_runs WHERE status = 'applied' AND source_kind = 'fingerprint_xls' "
        " ORDER BY COALESCE(finished_at, updated_at) DESC, id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None
