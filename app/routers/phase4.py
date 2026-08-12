"""Operational leave, sick-leave and replacement mutation surface."""
from __future__ import annotations

from datetime import date
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import config, db
from app.services import leave_operations as leave, replacement_operations as replacement
from app.services.xls_pipeline import DemoContextRefused, ensure_import_allowed

router=APIRouter(prefix="/api/v1",tags=["leave-replacement"])

class LeaveWrite(BaseModel):
    employeeId:int; leaveType:str; startDate:date; endDate:date; portion:str="full"
    reason:str|None=None; evidenceReceived:bool=False; evidenceStartDate:date|None=None
    evidenceEndDate:date|None=None; evidenceNote:str|None=None; evidenceCheckedDate:date|None=None
class Reason(BaseModel): reason:str=Field(min_length=2,max_length=500)
class ReplacementWrite(BaseModel):
    absentEmployeeId:int|None=None; replacementEmployeeId:int; startDate:date; endDate:date
    zone:str|None=None; shift:str="day"; leaveRequestId:int|None=None; note:str|None=None; status:str="planned"
class ReplacementPatch(BaseModel):
    absentEmployeeId:int|None=None; replacementEmployeeId:int|None=None; startDate:date|None=None; endDate:date|None=None
    zone:str|None=None; shift:str|None=None; note:str|None=None; status:str|None=None
class ChecklistPatch(BaseModel):
    keyReceived:bool|None=None; uniformReady:bool|None=None; orientationDone:bool|None=None
class StatusWrite(BaseModel): status:str; reason:str|None=None

def allowed():
    try: ensure_import_allowed()
    except DemoContextRefused as exc: raise HTTPException(409,str(exc)) from exc
def iso(value): return value.isoformat() if value else None
def write_error(exc): return HTTPException(409,str(exc))

@router.get("/leave-operations")
def leave_index(year:int|None=Query(default=None,ge=2000,le=2200)):
    conn=db.connect(config.DB_PATH,read_only=True)
    try:
        balance_year=year or date.today().year
        employees=[dict(r) for r in conn.execute("SELECT id,employee_code,name,status,hire_date,end_date,zone FROM employees ORDER BY name,id")]
        return {
            "leaves":leave.list_leave(conn,year),
            "employees":employees,
            "balanceYear":balance_year,
            "balances":[leave.balance(conn,row["id"],balance_year) for row in employees],
        }
    finally: conn.close()

@router.get("/leave-balances/{employee_id}/{year}")
def leave_balance(employee_id:int,year:int):
    conn=db.connect(config.DB_PATH,read_only=True)
    try:return leave.balance(conn,employee_id,year)
    finally:conn.close()

@router.post("/leave-operations",status_code=201)
def leave_create(body:LeaveWrite):
    allowed(); conn=db.connect(config.DB_PATH)
    try:
        with conn:return leave.create_leave(conn,employee_id=body.employeeId,leave_type=body.leaveType,start_date=iso(body.startDate),end_date=iso(body.endDate),portion=body.portion,reason=body.reason,evidence_received=body.evidenceReceived,evidence_start_date=iso(body.evidenceStartDate),evidence_end_date=iso(body.evidenceEndDate),evidence_note=body.evidenceNote,evidence_checked_date=iso(body.evidenceCheckedDate))
    except leave.LeaveError as exc:raise write_error(exc)
    finally:conn.close()

@router.post("/leave-operations/{leave_id}/approve")
def leave_approve(leave_id:int):
    allowed();conn=db.connect(config.DB_PATH)
    try:
        with conn:return leave.approve_leave(conn,leave_id)
    except leave.LeaveError as exc:raise write_error(exc)
    finally:conn.close()

@router.put("/leave-operations/{leave_id}")
def leave_correct(leave_id:int,body:LeaveWrite):
    allowed();conn=db.connect(config.DB_PATH)
    try:
        with conn:return leave.correct_leave(conn,leave_id,employee_id=body.employeeId,leave_type=body.leaveType,start_date=iso(body.startDate),end_date=iso(body.endDate),portion=body.portion,reason=body.reason or "휴가 정정",evidence_received=body.evidenceReceived,evidence_start_date=iso(body.evidenceStartDate),evidence_end_date=iso(body.evidenceEndDate),evidence_note=body.evidenceNote,evidence_checked_date=iso(body.evidenceCheckedDate))
    except leave.LeaveError as exc:raise write_error(exc)
    finally:conn.close()

@router.post("/leave-operations/{leave_id}/cancel")
def leave_cancel(leave_id:int,body:Reason):
    allowed();conn=db.connect(config.DB_PATH)
    try:
        with conn:return leave.cancel_leave(conn,leave_id,body.reason)
    except leave.LeaveError as exc:raise write_error(exc)
    finally:conn.close()

@router.get("/replacement-operations")
def replacement_index():
    conn=db.connect(config.DB_PATH,read_only=True)
    try:return {"assignments":replacement.list_assignments(conn),"employees":[dict(r) for r in conn.execute("SELECT id,employee_code,name,status,hire_date,end_date,zone FROM employees ORDER BY name,id")]}
    finally:conn.close()

@router.post("/replacement-operations",status_code=201)
def replacement_create(body:ReplacementWrite):
    allowed();conn=db.connect(config.DB_PATH)
    try:
        with conn:return replacement.create_assignment(conn,absent_employee_id=body.absentEmployeeId,replacement_employee_id=body.replacementEmployeeId,start_date=iso(body.startDate),end_date=iso(body.endDate),zone=body.zone,shift=body.shift,leave_request_id=body.leaveRequestId,note=body.note,status=body.status)
    except replacement.ReplacementError as exc:raise write_error(exc)
    finally:conn.close()

@router.patch("/replacement-operations/{assignment_id}")
def replacement_patch(assignment_id:int,body:ReplacementPatch):
    allowed();changes={k:v for k,v in body.model_dump(exclude_unset=True).items()};changes={k:iso(v) if isinstance(v,date) else v for k,v in changes.items()};conn=db.connect(config.DB_PATH)
    try:
        with conn:return replacement.update_assignment(conn,assignment_id,changes)
    except replacement.ReplacementError as exc:raise write_error(exc)
    finally:conn.close()

@router.patch("/replacement-operations/{assignment_id}/checklist")
def checklist_patch(assignment_id:int,body:ChecklistPatch):
    allowed();changes=body.model_dump(exclude_unset=True);conn=db.connect(config.DB_PATH)
    try:
        with conn:return replacement.patch_checklist(conn,assignment_id,changes)
    except replacement.ReplacementError as exc:raise write_error(exc)
    finally:conn.close()

@router.post("/replacement-operations/{assignment_id}/status")
def replacement_status(assignment_id:int,body:StatusWrite):
    allowed();conn=db.connect(config.DB_PATH)
    try:
        with conn:return replacement.set_status(conn,assignment_id,body.status,reason=body.reason)
    except replacement.ReplacementError as exc:raise write_error(exc)
    finally:conn.close()
