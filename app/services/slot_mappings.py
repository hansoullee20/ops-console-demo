"""Operational management of date-scoped fingerprint terminal slots."""
from __future__ import annotations
import sqlite3
from datetime import date

class MappingError(ValueError): pass

def list_mappings(conn: sqlite3.Connection) -> dict:
    employees=[dict(r) for r in conn.execute("SELECT id, employee_code, name, status FROM employees ORDER BY name, id")]
    mappings=[dict(r) for r in conn.execute("""SELECT t.id,t.terminal_id,t.slot_code,t.employee_id,t.effective_from,t.effective_to,t.status,e.name AS employee_name FROM terminal_slots t LEFT JOIN employees e ON e.id=t.employee_id ORDER BY t.slot_code,t.effective_from,t.id""")]
    today=date.today().isoformat()
    for row in mappings:
        row["range_status"]="future" if row["effective_from"]>today else "expired" if row["effective_to"] and row["effective_to"]<today else "active"
    discovered={r[0] for r in conn.execute("SELECT DISTINCT terminal_slot_code FROM punch_events")}
    discovered.update(r[0] for r in conn.execute("SELECT DISTINCT slot_code FROM terminal_slots"))
    return {"slots":sorted(discovered),"mappings":mappings,"employees":employees}

def create_mapping(conn: sqlite3.Connection, *, slot_code:str, employee_id:int, effective_from:str, effective_to:str|None=None, terminal_id:str="default") -> int:
    slot_code=slot_code.strip(); effective_to=effective_to or None
    if not slot_code or not effective_from: raise MappingError("슬롯과 적용 시작일이 필요합니다.")
    if effective_to and effective_to < effective_from: raise MappingError("적용 종료일은 시작일보다 빠를 수 없습니다.")
    if conn.execute("SELECT 1 FROM employees WHERE id=?",(employee_id,)).fetchone() is None: raise MappingError("선택한 직원을 찾을 수 없습니다.")
    overlap=conn.execute("""SELECT id FROM terminal_slots WHERE terminal_id=? AND slot_code=? AND COALESCE(effective_to,'9999-12-31')>=? AND COALESCE(?, '9999-12-31')>=effective_from LIMIT 1""",(terminal_id,slot_code,effective_from,effective_to)).fetchone()
    if overlap: raise MappingError("이 슬롯에는 선택한 기간과 겹치는 기존 연결이 있습니다.")
    cur=conn.execute("""INSERT INTO terminal_slots(terminal_id,slot_code,employee_id,effective_from,effective_to,status) VALUES(?,?,?,?,?,'mapped')""",(terminal_id,slot_code,employee_id,effective_from,effective_to))
    return int(cur.lastrowid)

def close_mapping(conn: sqlite3.Connection, mapping_id:int, effective_to:str) -> None:
    row=conn.execute("SELECT effective_from,effective_to FROM terminal_slots WHERE id=?",(mapping_id,)).fetchone()
    if row is None: raise MappingError("연결 이력을 찾을 수 없습니다.")
    if row["effective_to"] is not None: raise MappingError("이미 종료된 연결입니다.")
    if effective_to < row["effective_from"]: raise MappingError("종료일은 시작일보다 빠를 수 없습니다.")
    conn.execute("UPDATE terminal_slots SET effective_to=? WHERE id=?",(effective_to,mapping_id))

