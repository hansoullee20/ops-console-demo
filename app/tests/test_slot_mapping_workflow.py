from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app import config, db
from app.main import create_app
from app.services import slot_mappings, xls_pipeline
from app.tests.fixtures.terminal_xls import SlotSpec, build_export

def add_employee(conn, code, name):
    return conn.execute("INSERT INTO employees(employee_code,name,hire_date) VALUES(?,?,?)",(code,name,"2020-01-01")).lastrowid

@pytest.fixture
def operational(monkeypatch,migrated_db,tmp_path):
    conn=db.connect(migrated_db); conn.execute("INSERT INTO app_meta(key,value) VALUES('data_context','operational') ON CONFLICT(key) DO UPDATE SET value='operational'"); a=add_employee(conn,"A","가상 직원 A"); b=add_employee(conn,"B","가상 직원 B"); conn.commit(); conn.close()
    monkeypatch.setattr(config,"DB_PATH",migrated_db); monkeypatch.setattr(config,"UPLOADS_DIR",tmp_path/"uploads"); monkeypatch.setattr(config,"BACKUPS_DIR",tmp_path/"backups"); monkeypatch.setattr(config,"ALLOW_DEMO_IMPORT",False)
    return migrated_db,a,b

def test_date_scoped_mapping_and_history_are_preserved(operational):
    path,a,b=operational; conn=db.connect(path)
    slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-01-01",effective_to="2026-07-31")
    slot_mappings.create_mapping(conn,slot_code="001",employee_id=b,effective_from="2026-08-01")
    conn.commit(); rows=slot_mappings.list_mappings(conn)["mappings"]; conn.close()
    assert [(r["employee_id"],r["effective_from"],r["effective_to"]) for r in rows]==[(a,"2026-01-01","2026-07-31"),(b,"2026-08-01",None)]

def test_july_and_august_exports_resolve_each_historical_holder(operational,tmp_path):
    path,a,b=operational; conn=db.connect(path)
    slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-01-01",effective_to="2026-07-31")
    slot_mappings.create_mapping(conn,slot_code="001",employee_id=b,effective_from="2026-08-01"); conn.commit(); conn.close()
    july=build_export(tmp_path/"july.xls",year=2026,month=7,slots=[SlotSpec("001","가상",{1:["07:00","16:00"]})])
    august=build_export(tmp_path/"august.xls",year=2026,month=8,slots=[SlotSpec("001","가상",{1:["07:00","16:00"]})])
    assert xls_pipeline.preview_import(july,db_path=path,uploads_dir=tmp_path/"up1").slots[0]["employeeIds"]==[a]
    assert xls_pipeline.preview_import(august,db_path=path,uploads_dir=tmp_path/"up2").slots[0]["employeeIds"]==[b]

def test_overlapping_mapping_is_rejected(operational):
    path,a,b=operational; conn=db.connect(path); slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-01-01",effective_to="2026-07-31")
    with pytest.raises(slot_mappings.MappingError): slot_mappings.create_mapping(conn,slot_code="001",employee_id=b,effective_from="2026-07-01")
    assert conn.execute("SELECT COUNT(*) FROM terminal_slots").fetchone()[0]==1; conn.close()

def test_unmapped_preview_mapping_refresh_and_apply(operational,tmp_path):
    path,a,_=operational; source=build_export(tmp_path/"aug.xls",year=2026,month=8,slots=[SlotSpec("001","가상 슬롯",{1:["07:00","16:00"]})])
    first=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads"); assert first.slots[0]["status"]=="unmapped"
    conn=db.connect(path); slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-08-01"); conn.commit(); conn.close()
    refreshed=xls_pipeline.refresh_preview(first.import_run_id,db_path=path); assert refreshed.confirmation_token!=first.confirmation_token and refreshed.slots[0]["employeeIds"]==[a]
    result=xls_pipeline.apply_import(first.import_run_id,refreshed.confirmation_token,db_path=path,backups_dir=tmp_path/"backups"); assert result["inserted"]==2

def test_mapping_http_rejects_invalid_interval(operational):
    path,a,_=operational
    with TestClient(create_app()) as client:
        response=client.post("/api/v1/terminal-slots",json={"slotCode":"001","employeeId":a,"effectiveFrom":"2026-08-10","effectiveTo":"2026-08-01"})
        assert response.status_code==409

def test_mapping_batch_is_atomic_when_one_interval_overlaps(operational):
    path,a,b=operational; conn=db.connect(path); slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-01-01"); conn.commit(); conn.close()
    with TestClient(create_app()) as client:
        response=client.post("/api/v1/terminal-slots/batch",json={"mappings":[{"slotCode":"002","employeeId":b,"effectiveFrom":"2026-08-01"},{"slotCode":"001","employeeId":b,"effectiveFrom":"2026-08-01"}]})
        assert response.status_code==409
    conn=db.connect(path); assert conn.execute("SELECT COUNT(*) FROM terminal_slots WHERE slot_code='002'").fetchone()[0]==0; conn.close()

def test_frontend_validates_interval_before_saving():
    script=Path("import-ui.js").read_text(encoding="utf-8-sig")
    assert "to&&to<from" in script
    assert "OPS_SAVE_MAPPINGS" in script and "'/batch'" in script

def test_mapping_write_is_refused_on_demo_database(monkeypatch,migrated_db,tmp_path):
    from app.seed.demo_dataset import seed_demo_database
    seed_demo_database(migrated_db)
    monkeypatch.setattr(config,"DB_PATH",migrated_db); monkeypatch.setattr(config,"ALLOW_DEMO_IMPORT",False)
    with TestClient(create_app()) as client:
        response=client.post("/api/v1/terminal-slots",json={"slotCode":"099","employeeId":1,"effectiveFrom":"2026-08-01"})
    assert response.status_code==409

def test_partial_mapping_is_blocking_and_lists_uncovered_punch_dates(operational,tmp_path):
    path,a,_=operational
    source=build_export(tmp_path/"partial.xls",year=2026,month=8,slots=[SlotSpec("001","가상 슬롯",{1:["07:00"],5:["16:00"]})])
    conn=db.connect(path); slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-08-05"); conn.commit(); conn.close()
    preview=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads")
    assert preview.slots[0]["status"]=="partial_unmapped"
    assert preview.slots[0]["uncoveredDates"]==["2026-08-01"]
    assert any(f["code"]=="unmapped_punch_dates" and f["severity"]=="blocking" for f in preview.findings)
    assert preview.can_apply is False

def test_mapping_handoff_finding_does_not_hide_a_gap(operational,tmp_path):
    path,a,b=operational
    source=build_export(tmp_path/"gap.xls",year=2026,month=8,slots=[SlotSpec("001","가상 슬롯",{3:["07:00"],4:["07:00"],5:["07:00"]})])
    conn=db.connect(path)
    slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-08-01",effective_to="2026-08-03")
    slot_mappings.create_mapping(conn,slot_code="001",employee_id=b,effective_from="2026-08-05")
    conn.commit(); conn.close()
    preview=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads")
    assert {f["code"] for f in preview.findings}>={"slot_changed_hands","unmapped_punch_dates"}
    assert preview.slots[0]["uncoveredDates"]==["2026-08-04"]
    assert preview.can_apply is False

def test_wrong_mapping_can_be_cancelled_then_corrected_and_audited(operational,tmp_path):
    path,a,b=operational
    source=build_export(tmp_path/"correct.xls",year=2026,month=8,slots=[SlotSpec("001","가상 슬롯",{1:["07:00","16:00"]})])
    first=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads")
    conn=db.connect(path)
    wrong=slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-08-01")
    conn.commit(); conn.close()
    wrong_preview=xls_pipeline.refresh_preview(first.import_run_id,db_path=path)
    conn=db.connect(path)
    slot_mappings.correct_mapping(conn,wrong,b,"잘못 선택")
    conn.commit(); conn.close()
    corrected=xls_pipeline.refresh_preview(first.import_run_id,db_path=path)
    assert corrected.slots[0]["employeeIds"]==[b]
    assert corrected.confirmation_token!=wrong_preview.confirmation_token
    with pytest.raises(xls_pipeline.ImportError_,match="confirmation token"):
        xls_pipeline.apply_import(first.import_run_id,wrong_preview.confirmation_token,db_path=path,backups_dir=tmp_path/"backups")
    result=xls_pipeline.apply_import(first.import_run_id,corrected.confirmation_token,db_path=path,backups_dir=tmp_path/"backups")
    assert result["inserted"]==2
    conn=db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM punch_events WHERE employee_id=?",(b,)).fetchone()[0]==2
    assert [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE entity_type='terminal_slots' ORDER BY id")]==["terminal_slot.create","terminal_slot.correct"]
    conn.close()

def test_mapping_used_by_active_import_requires_rollback_before_cancel(operational,tmp_path):
    path,a,_=operational
    source=build_export(tmp_path/"used.xls",year=2026,month=8,slots=[SlotSpec("001","가상 슬롯",{1:["07:00","16:00"]})])
    conn=db.connect(path); mapping=slot_mappings.create_mapping(conn,slot_code="001",employee_id=a,effective_from="2026-08-01"); conn.commit(); conn.close()
    preview=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads")
    xls_pipeline.apply_import(preview.import_run_id,preview.confirmation_token,db_path=path,backups_dir=tmp_path/"backups")
    conn=db.connect(path)
    with pytest.raises(slot_mappings.MappingError,match="먼저.*되돌리"):
        slot_mappings.cancel_mapping(conn,mapping,"잘못 선택")
    conn.close()

def test_historical_employee_is_returned_with_status_and_end_date(operational):
    path,_,_=operational
    conn=db.connect(path)
    departed=add_employee(conn,"OLD","과거 직원")
    conn.execute("UPDATE employees SET status='terminated', end_date='2025-12-31' WHERE id=?",(departed,))
    conn.commit()
    employee=next(e for e in slot_mappings.list_mappings(conn)["employees"] if e["id"]==departed)
    conn.close()
    assert employee["status"]=="terminated" and employee["end_date"]=="2025-12-31"

def _apply_august_mapping_fixture(path,tmp_path,employee_id,days=(1,10)):
    conn=db.connect(path)
    mapping_id=slot_mappings.create_mapping(conn,slot_code="001",employee_id=employee_id,effective_from="2026-01-01")
    conn.commit(); conn.close()
    punches={day:["07:00","16:00"] for day in days}
    source=build_export(tmp_path/"close.xls",year=2026,month=8,slots=[SlotSpec("001","가상 슬롯",punches)])
    preview=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads")
    xls_pipeline.apply_import(preview.import_run_id,preview.confirmation_token,db_path=path,backups_dir=tmp_path/"backups")
    return mapping_id,preview.import_run_id,source

def test_close_rejects_end_date_that_excludes_active_imported_punch(operational,tmp_path):
    path,a,_=operational
    mapping_id,_,_=_apply_august_mapping_fixture(path,tmp_path,a,days=(1,))
    conn=db.connect(path)
    audit_before=conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='terminal_slot.close'").fetchone()[0]
    with pytest.raises(slot_mappings.MappingError,match="먼저.*되돌리"):
        slot_mappings.close_mapping(conn,mapping_id,"2026-07-31")
    row=conn.execute("SELECT effective_to FROM terminal_slots WHERE id=?",(mapping_id,)).fetchone()
    audit_after=conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='terminal_slot.close'").fetchone()[0]
    conn.close()
    assert row["effective_to"] is None
    assert audit_after==audit_before

def test_close_allows_last_active_punch_date_and_writes_audit(operational,tmp_path):
    path,a,_=operational
    mapping_id,_,_=_apply_august_mapping_fixture(path,tmp_path,a)
    conn=db.connect(path)
    slot_mappings.close_mapping(conn,mapping_id,"2026-08-10")
    conn.commit()
    assert conn.execute("SELECT effective_to FROM terminal_slots WHERE id=?",(mapping_id,)).fetchone()[0]=="2026-08-10"
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='terminal_slot.close' AND entity_id=?",(mapping_id,)).fetchone()[0]==1
    conn.close()

def test_after_rollback_close_can_exclude_old_punches_and_new_mapping_wins(operational,tmp_path):
    path,a,b=operational
    mapping_id,run_id,source=_apply_august_mapping_fixture(path,tmp_path,a,days=(1,))
    xls_pipeline.rollback_import(run_id,"직원 연결 정정",db_path=path)
    conn=db.connect(path)
    slot_mappings.close_mapping(conn,mapping_id,"2026-07-31")
    slot_mappings.create_mapping(conn,slot_code="001",employee_id=b,effective_from="2026-08-01")
    conn.commit(); conn.close()
    preview=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads-2")
    assert preview.slots[0]["employeeIds"]==[b]
    assert preview.reactivatable_punches==2

def test_close_mapping_http_rejects_excluding_active_punch_and_allows_boundary(operational,tmp_path):
    path,a,_=operational
    mapping_id,_,_=_apply_august_mapping_fixture(path,tmp_path,a)
    with TestClient(create_app()) as client:
        rejected=client.post(f"/api/v1/terminal-slots/{mapping_id}/close",json={"effectiveTo":"2026-07-31"})
        allowed=client.post(f"/api/v1/terminal-slots/{mapping_id}/close",json={"effectiveTo":"2026-08-10"})
    assert rejected.status_code==409
    assert "먼저" in rejected.json()["detail"]
    assert allowed.status_code==200
