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
