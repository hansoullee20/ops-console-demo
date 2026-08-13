"""Phase 4.25 operational safety HTTP surface."""
from datetime import date
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app import config,db
from app.services import operational_safety as safety
from app.services.xls_pipeline import ensure_import_allowed,DemoContextRefused

router=APIRouter(prefix="/api/v1",tags=["operational-safety"])
def allowed():
    try:ensure_import_allowed()
    except DemoContextRefused as exc:raise HTTPException(409,str(exc)) from exc
def err(exc):return HTTPException(409,str(exc))
class Lifecycle(BaseModel):note:str|None=None;actor:str="operator"
class Adjustment(BaseModel):
    employeeId:int;workDate:date;recognizedInAt:str|None=None;recognizedOutAt:str|None=None
    resultingStatus:str="normal";reason:str=Field(min_length=2,max_length=500);referenceNote:str|None=None;supersedesId:int|None=None
class EndAdjustment(BaseModel):reason:str=Field(min_length=2,max_length=500);actor:str="operator"
class EndSchedule(BaseModel):reason:str=Field(min_length=2,max_length=500);actor:str="operator"
class Schedule(BaseModel):
    effectiveFrom:date;effectiveTo:date|None=None;weekdayMask:str;expectedStartTime:str|None=None;expectedEndTime:str|None=None;actor:str="operator"
class DateOverride(BaseModel):
    workDate:date;isScheduled:bool;expectedStartTime:str|None=None;expectedEndTime:str|None=None;label:str|None=None;supersedesId:int|None=None;actor:str="operator"

@router.get("/operations/exceptions")
def exceptions(status:str|None=None,employeeId:int|None=None,start:date|None=None,end:date|None=None,exceptionType:str|None=None,severity:str|None=None,sourceQualityOnly:bool=False):
    c=db.connect(config.DB_PATH,read_only=True)
    try:return {"exceptions":safety.list_exceptions(c,status=status,employee_id=employeeId,start=str(start) if start else None,end=str(end) if end else None,code=exceptionType,severity=severity,source_only=sourceQualityOnly)}
    finally:c.close()
@router.get("/operations/exceptions/{exception_id}")
def exception_detail(exception_id:int):
    c=db.connect(config.DB_PATH,read_only=True)
    try:return safety.exception_detail(c,exception_id)
    except safety.SafetyError as exc:raise HTTPException(404,str(exc))
    finally:c.close()
def transition(exception_id,body,to):
    allowed();c=db.connect(config.DB_PATH)
    try:
        with c:return safety.transition_exception(c,exception_id,to,body.note,body.actor)
    except safety.SafetyError as exc:raise err(exc)
    finally:c.close()
@router.post("/operations/exceptions/{exception_id}/acknowledge")
def acknowledge(exception_id:int,body:Lifecycle):return transition(exception_id,body,"acknowledged")
@router.post("/operations/exceptions/{exception_id}/resolve")
def resolve(exception_id:int,body:Lifecycle):return transition(exception_id,body,"resolved")
@router.post("/operations/exceptions/{exception_id}/waive")
def waive(exception_id:int,body:Lifecycle):return transition(exception_id,body,"waived")

@router.get("/operations/read-model")
def read_model(start:date,end:date,status:str|None=None,employeeId:int|None=None,exceptionType:str|None=None,severity:str|None=None,sourceQualityOnly:bool=False):
    allowed();c=db.connect(config.DB_PATH)
    try:
        with c:return safety.operations_read_model(c,str(start),str(end),status=status,employee_id=employeeId,code=exceptionType,severity=severity,source_only=sourceQualityOnly)
    finally:c.close()
@router.get("/operations/source-quality")
def source_quality(start:date,end:date):
    c=db.connect(config.DB_PATH,read_only=True)
    try:return {"observations":[dict(r) for r in c.execute("SELECT * FROM source_quality_observations WHERE work_date BETWEEN ? AND ? ORDER BY id",(str(start),str(end)))]}
    finally:c.close()

@router.get("/attendance/manual-adjustments")
def adjustments(employeeId:int|None=None):
    c=db.connect(config.DB_PATH,read_only=True)
    try:return {"adjustments":[dict(r) for r in c.execute("SELECT * FROM manual_attendance_adjustments WHERE (? IS NULL OR employee_id=?) ORDER BY id",(employeeId,employeeId))]}
    finally:c.close()
@router.post("/attendance/manual-adjustments",status_code=201)
def adjustment_create(body:Adjustment):
    allowed();c=db.connect(config.DB_PATH)
    try:
        with c:return safety.create_adjustment(c,employee_id=body.employeeId,work_date=str(body.workDate),recognized_in_at=body.recognizedInAt,recognized_out_at=body.recognizedOutAt,resulting_status=body.resultingStatus,reason=body.reason,reference_note=body.referenceNote,supersedes_id=body.supersedesId)
    except (safety.SafetyError,ValueError) as exc:raise err(exc)
    finally:c.close()
@router.post("/attendance/manual-adjustments/{adjustment_id}/supersede")
def adjustment_supersede(adjustment_id:int,body:Adjustment):
    body.supersedesId=adjustment_id;return adjustment_create(body)
@router.post("/attendance/manual-adjustments/{adjustment_id}/cancel")
def adjustment_cancel(adjustment_id:int,body:EndAdjustment):return end_adjustment(adjustment_id,body,"cancelled")
@router.post("/attendance/manual-adjustments/{adjustment_id}/void")
def adjustment_void(adjustment_id:int,body:EndAdjustment):return end_adjustment(adjustment_id,body,"voided")
def end_adjustment(adjustment_id,body,status):
    allowed();c=db.connect(config.DB_PATH)
    try:
        with c:return safety.end_adjustment(c,adjustment_id,status,body.reason,body.actor)
    except safety.SafetyError as exc:raise err(exc)
    finally:c.close()

@router.get("/employees/{employee_id}/schedules")
def schedules(employee_id:int):
    c=db.connect(config.DB_PATH,read_only=True)
    try:return {"schedules":[dict(r) for r in c.execute("SELECT * FROM employee_work_schedules WHERE employee_id=? ORDER BY effective_from,id",(employee_id,))],"dateOverrides":[dict(r) for r in c.execute("SELECT * FROM employee_schedule_dates WHERE employee_id=? ORDER BY work_date,id",(employee_id,))]}
    finally:c.close()
@router.post("/employees/{employee_id}/schedules",status_code=201)
def schedule_create(employee_id:int,body:Schedule):
    allowed();c=db.connect(config.DB_PATH)
    try:
        c.execute("BEGIN IMMEDIATE");result=safety.create_schedule(c,employee_id=employee_id,effective_from=str(body.effectiveFrom),effective_to=str(body.effectiveTo) if body.effectiveTo else None,weekday_mask=body.weekdayMask,expected_start_time=body.expectedStartTime,expected_end_time=body.expectedEndTime,actor=body.actor);c.commit();return result
    except safety.SafetyError as exc:c.rollback();raise err(exc)
    finally:c.close()
@router.post("/employees/{employee_id}/schedules/{schedule_id}/retire")
def schedule_retire(employee_id:int,schedule_id:int,body:EndSchedule):
    allowed();c=db.connect(config.DB_PATH)
    try:
        with c:
            row=c.execute("SELECT employee_id FROM employee_work_schedules WHERE id=?",(schedule_id,)).fetchone()
            if not row or row[0]!=employee_id:raise safety.SafetyError("schedule not found")
            return safety.retire_schedule(c,schedule_id,body.reason,body.actor)
    except safety.SafetyError as exc:raise err(exc)
    finally:c.close()
@router.post("/employees/{employee_id}/schedule-dates",status_code=201)
def schedule_date(employee_id:int,body:DateOverride):
    allowed();c=db.connect(config.DB_PATH)
    try:
        with c:return safety.set_schedule_date(c,employee_id=employee_id,work_date=str(body.workDate),is_scheduled=body.isScheduled,expected_start_time=body.expectedStartTime,expected_end_time=body.expectedEndTime,label=body.label,actor=body.actor,supersedes_id=body.supersedesId)
    except safety.SafetyError as exc:raise err(exc)
    finally:c.close()
@router.post("/employees/{employee_id}/schedule-dates/{override_id}/cancel")
def schedule_date_cancel(employee_id:int,override_id:int,body:EndSchedule):
    allowed();c=db.connect(config.DB_PATH)
    try:
        with c:
            row=c.execute("SELECT employee_id FROM employee_schedule_dates WHERE id=?",(override_id,)).fetchone()
            if not row or row[0]!=employee_id:raise safety.SafetyError("date override not found")
            return safety.cancel_schedule_date(c,override_id,body.reason,body.actor)
    except safety.SafetyError as exc:raise err(exc)
    finally:c.close()
