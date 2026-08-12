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
    if row is None or row["status"] == "retired":
        raise MappingError("연결 이력을 찾을 수 없습니다.")
    if row["effective_to"] is not None:
        raise MappingError("이미 종료일이 있는 연결입니다.")
    if effective_to < row["effective_from"]:
        raise MappingError("종료일은 시작일보다 빠를 수 없습니다.")
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
        raise MappingError("연결 취소 이유를 입력하십시오.")
    row = conn.execute("SELECT * FROM terminal_slots WHERE id = ?", (mapping_id,)).fetchone()
    if row is None or row["status"] == "retired":
        raise MappingError("취소할 연결 이력을 찾을 수 없습니다.")
    used = conn.execute(
        """SELECT 1 FROM punch_events
            WHERE terminal_id = ? AND terminal_slot_code = ? AND employee_id = ?
              AND work_date >= ?
              AND (? IS NULL OR work_date <= ?)
              AND rolled_back_at IS NULL
            LIMIT 1""",
        (
            row["terminal_id"], row["slot_code"], row["employee_id"],
            row["effective_from"], row["effective_to"], row["effective_to"],
        ),
    ).fetchone()
    if used:
        raise MappingError("이미 반영된 지문이 이 연결을 사용합니다. 먼저 해당 가져오기를 되돌리십시오.")
    before = dict(row)
    conn.execute("UPDATE terminal_slots SET status = 'retired' WHERE id = ?", (mapping_id,))
    after = dict(conn.execute("SELECT * FROM terminal_slots WHERE id = ?", (mapping_id,)).fetchone())
    _audit(conn, "terminal_slot.cancel", mapping_id, before, after, reason.strip(), actor_id)


def correct_mapping(
    conn: sqlite3.Connection, mapping_id: int, employee_id: int, reason: str,
    *, actor_id: str = "operator",
) -> None:
    """Explicitly correct an unused mapping while preserving before/after audit evidence."""
    if len(reason.strip()) < 2:
        raise MappingError("연결 정정 이유를 입력하십시오.")
    if conn.execute("SELECT 1 FROM employees WHERE id = ?", (employee_id,)).fetchone() is None:
        raise MappingError("선택한 직원을 찾을 수 없습니다.")
    row = conn.execute("SELECT * FROM terminal_slots WHERE id = ?", (mapping_id,)).fetchone()
    if row is None or row["status"] != "mapped":
        raise MappingError("정정할 연결 이력을 찾을 수 없습니다.")
    used = conn.execute(
        """SELECT 1 FROM punch_events
            WHERE terminal_id = ? AND terminal_slot_code = ? AND employee_id = ?
              AND work_date >= ? AND (? IS NULL OR work_date <= ?)
              AND rolled_back_at IS NULL LIMIT 1""",
        (row["terminal_id"], row["slot_code"], row["employee_id"],
         row["effective_from"], row["effective_to"], row["effective_to"]),
    ).fetchone()
    if used:
        raise MappingError("이미 반영된 지문이 이 연결을 사용합니다. 먼저 해당 가져오기를 되돌리십시오.")
    before = dict(row)
    conn.execute("UPDATE terminal_slots SET employee_id = ? WHERE id = ?", (employee_id, mapping_id))
    after = dict(conn.execute("SELECT * FROM terminal_slots WHERE id = ?", (mapping_id,)).fetchone())
    _audit(conn, "terminal_slot.correct", mapping_id, before, after, reason.strip(), actor_id)
