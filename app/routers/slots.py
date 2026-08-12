from __future__ import annotations
from datetime import date
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app import config, db
from app.services import slot_mappings, xls_pipeline

router=APIRouter(prefix="/api/v1/terminal-slots",tags=["terminal-slots"])
class MappingCreate(BaseModel):
    slotCode:str=Field(min_length=1,max_length=30)
    employeeId:int
    effectiveFrom:date
    effectiveTo:date|None=None

class MappingBatch(BaseModel):
    mappings:list[MappingCreate]=Field(min_length=1,max_length=100)
class MappingClose(BaseModel):
    effectiveTo:date
class MappingCancel(BaseModel):
    reason:str=Field(min_length=2,max_length=500)
class MappingCorrect(BaseModel):
    employeeId:int
    reason:str=Field(min_length=2,max_length=500)

@router.get("")
def index():
    conn=db.connect(config.DB_PATH,read_only=True)
    try:return slot_mappings.list_mappings(conn)
    finally:conn.close()

@router.post("",status_code=201)
def create(body:MappingCreate):
    try: xls_pipeline.ensure_import_allowed()
    except xls_pipeline.DemoContextRefused as exc: raise HTTPException(409,str(exc)) from exc
    conn=db.connect(config.DB_PATH)
    try:
        with conn:
            mapping_id=slot_mappings.create_mapping(conn,slot_code=body.slotCode,employee_id=body.employeeId,effective_from=body.effectiveFrom.isoformat(),effective_to=body.effectiveTo.isoformat() if body.effectiveTo else None)
        return {"id":mapping_id}
    except slot_mappings.MappingError as exc: raise HTTPException(409,str(exc)) from exc
    finally:conn.close()

@router.post("/batch",status_code=201)
def create_batch(body:MappingBatch):
    try: xls_pipeline.ensure_import_allowed()
    except xls_pipeline.DemoContextRefused as exc: raise HTTPException(409,str(exc)) from exc
    conn=db.connect(config.DB_PATH)
    try:
        with conn:
            ids=[slot_mappings.create_mapping(conn,slot_code=item.slotCode,employee_id=item.employeeId,effective_from=item.effectiveFrom.isoformat(),effective_to=item.effectiveTo.isoformat() if item.effectiveTo else None) for item in body.mappings]
        return {"ids":ids}
    except slot_mappings.MappingError as exc: raise HTTPException(409,str(exc)) from exc
    finally:conn.close()

@router.post("/{mapping_id}/close")
def close(mapping_id:int,body:MappingClose):
    try: xls_pipeline.ensure_import_allowed()
    except xls_pipeline.DemoContextRefused as exc: raise HTTPException(409,str(exc)) from exc
    conn=db.connect(config.DB_PATH)
    try:
        with conn: slot_mappings.close_mapping(conn,mapping_id,body.effectiveTo.isoformat())
        return {"id":mapping_id,"effectiveTo":body.effectiveTo.isoformat()}
    except slot_mappings.MappingError as exc: raise HTTPException(409,str(exc)) from exc
    finally:conn.close()

@router.post("/{mapping_id}/cancel")
def cancel(mapping_id:int,body:MappingCancel):
    try: xls_pipeline.ensure_import_allowed()
    except xls_pipeline.DemoContextRefused as exc: raise HTTPException(409,str(exc)) from exc
    conn=db.connect(config.DB_PATH)
    try:
        with conn: slot_mappings.cancel_mapping(conn,mapping_id,body.reason)
        return {"id":mapping_id,"status":"retired"}
    except slot_mappings.MappingError as exc: raise HTTPException(409,str(exc)) from exc
    finally:conn.close()

@router.post("/{mapping_id}/correct")
def correct(mapping_id:int,body:MappingCorrect):
    try: xls_pipeline.ensure_import_allowed()
    except xls_pipeline.DemoContextRefused as exc: raise HTTPException(409,str(exc)) from exc
    conn=db.connect(config.DB_PATH)
    try:
        with conn: slot_mappings.correct_mapping(conn,mapping_id,body.employeeId,body.reason)
        return {"id":mapping_id,"employeeId":body.employeeId}
    except slot_mappings.MappingError as exc: raise HTTPException(409,str(exc)) from exc
    finally:conn.close()
