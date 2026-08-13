from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3,pytest
from app import config,db,migrate
from app.main import create_app
from fastapi.testclient import TestClient
from app.services import operational_safety as safety,xls_pipeline
from app.tests.fixtures.terminal_xls import SlotSpec,build_export

@pytest.fixture
def operational(migrated_db):
    c=db.connect(migrated_db);c.execute("UPDATE app_meta SET value='operational' WHERE key='data_context'")
    a=c.execute("INSERT INTO employees(employee_code,name,hire_date,status,zone)VALUES('SAFE-A','가상 안전 A','2025-01-01','active','본관')").lastrowid
    b=c.execute("INSERT INTO employees(employee_code,name,hire_date,status,zone)VALUES('SAFE-B','가상 안전 B','2025-01-01','active','본관')").lastrowid
    c.commit();c.close();return migrated_db,a,b

def test_active_only_dedupe_and_append_only_events(operational):
    path,a,_=operational;c=db.connect(path)
    x=safety.ensure_exception(c,code="incomplete_day",severity="review",scope="employee",employee_id=a,work_date="2026-08-10",summary="검토",evidence=[{"evidence_type":"manual_manager_statement","entity_type":"note","reference_text":"one"}])
    same=safety.ensure_exception(c,code="incomplete_day",severity="review",scope="employee",employee_id=a,work_date="2026-08-10",summary="검토",evidence=[{"evidence_type":"manual_manager_statement","entity_type":"note","reference_text":"two"}])
    assert same["id"]==x["id"] and len(same["events"])==2
    safety.transition_exception(c,x["id"],"resolved","확인 완료")
    again=safety.ensure_exception(c,code="incomplete_day",severity="review",scope="employee",employee_id=a,work_date="2026-08-10",summary="재발")
    assert again["id"]!=x["id"] and again["previous_occurrence_id"]==x["id"]
    with pytest.raises(sqlite3.IntegrityError):c.execute("DELETE FROM exception_events WHERE exception_id=?",(x["id"],))
    with pytest.raises(sqlite3.IntegrityError):c.execute("UPDATE exception_evidence_links SET reference_text='x' WHERE exception_id=?",(x["id"],))
    c.close()

def test_multiple_exceptions_have_independent_lifecycle(operational):
    path,a,_=operational;c=db.connect(path)
    one=safety.ensure_exception(c,code="sick_leave_evidence_mismatch",severity="review",scope="employee",employee_id=a,work_date="2026-08-10",summary="증빙")
    two=safety.ensure_exception(c,code="leave_attendance_conflict",severity="review",scope="employee",employee_id=a,work_date="2026-08-10",summary="충돌")
    safety.transition_exception(c,one["id"],"resolved","증빙 확인")
    assert safety.exception_detail(c,two["id"])["status"]=="open";c.close()

def test_manual_adjustment_preserves_raw_and_supersedes_history(operational,tmp_path):
    path,a,_=operational;c=db.connect(path)
    first=safety.create_adjustment(c,employee_id=a,work_date="2026-08-10",recognized_in_at="08:00",recognized_out_at="16:00",reason="관리자 확인")
    second=safety.create_adjustment(c,employee_id=a,work_date="2026-08-10",recognized_in_at="08:10",recognized_out_at="16:10",reason="시간 정정",supersedes_id=first["id"])
    assert c.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0]==0
    assert c.execute("SELECT status FROM manual_attendance_adjustments WHERE id=?",(first["id"],)).fetchone()[0]=="superseded"
    assert c.execute("SELECT COUNT(*) FROM manual_attendance_adjustments WHERE status='active' AND employee_id=?",(a,)).fetchone()[0]==1
    # Unrelated later confirmation prevents cancellation from re-deriving it.
    c.execute("UPDATE attendance_days SET actual_in_at='09:00',confirmed_by='other-manager' WHERE employee_id=?",(a,));before=dict(c.execute("SELECT * FROM attendance_days WHERE employee_id=?",(a,)).fetchone())
    safety.end_adjustment(c,second["id"],"cancelled","entered in error")
    after=dict(c.execute("SELECT * FROM attendance_days WHERE employee_id=?",(a,)).fetchone())
    assert after["actual_in_at"]==before["actual_in_at"] and after["confirmed_by"]=="other-manager"
    c.close()

def test_later_xls_does_not_overwrite_manual_confirmation(operational,tmp_path):
    path,a,_=operational;c=db.connect(path);c.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status)VALUES('001',?,'2026-01-01','mapped')",(a,));safety.create_adjustment(c,employee_id=a,work_date="2026-08-10",recognized_in_at="08:00",recognized_out_at="16:00",reason="관리자 확인");c.commit();c.close()
    source=build_export(tmp_path/'manual.xls',year=2026,month=8,slots=[SlotSpec('001','Fictional',{10:['07:50','16:20']})]);p=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/'up');xls_pipeline.apply_import(p.import_run_id,p.confirmation_token,db_path=path,backups_dir=tmp_path/'back')
    c=db.connect(path);row=c.execute("SELECT source,actual_in_at,actual_out_at,confirmed_at FROM attendance_days WHERE employee_id=? AND work_date='2026-08-10'",(a,)).fetchone();assert tuple(row)==('manual','08:00','16:00',row['confirmed_at']);assert row['confirmed_at'];c.close()

def test_schedule_precedence_boundaries_and_overlap(operational):
    path,a,_=operational;c=db.connect(path);c.execute("INSERT INTO site_calendar(calendar_date,day_type,is_working,label)VALUES('2026-08-09','holiday',0,'가상 휴무')")
    s=safety.create_schedule(c,employee_id=a,effective_from='2026-08-01',effective_to='2026-08-31',weekday_mask='0,1,2,3,4')
    with pytest.raises(safety.SafetyError):safety.create_schedule(c,employee_id=a,effective_from='2026-08-15',effective_to=None,weekday_mask='0')
    safety.set_schedule_date(c,employee_id=a,work_date='2026-08-09',is_scheduled=True,label='특별 근무')
    resolved=safety.resolve_schedule(c,a,'2026-08-09');assert resolved['isScheduled'] and resolved['source']=='employee_date_override'
    assert safety.resolve_schedule(c,a,'2026-08-01')['source']=='employee_schedule'
    assert safety.resolve_schedule(c,a,'2026-08-31')['source']=='employee_schedule';c.close()

def test_source_quality_is_site_scoped_and_sunday_is_quiet(operational):
    path,a,_=operational;c=db.connect(path)
    safety.create_schedule(c,employee_id=a,effective_from='2026-08-03',effective_to='2026-08-09',weekday_mask='0,1,2,3,4')
    rid=c.execute("INSERT INTO import_runs(source_filename,source_sha256,stored_source_path,status)VALUES('fictional.xls','hash','x','applied')").lastrowid
    c.execute("INSERT INTO import_run_days(import_run_id,work_date,source_date_present,raw_punch_count,coverage_status)VALUES(?, '2026-08-03',1,0,'reported_zero')",(rid,));c.commit()
    safety.reconcile(c,'2026-08-03','2026-08-09')
    source=c.execute("SELECT scope,employee_id,exception_code FROM operational_exceptions WHERE exception_code='covered_but_zero_events'").fetchone();assert tuple(source)==('source',None,'covered_but_zero_events')
    assert not c.execute("SELECT 1 FROM operational_exceptions WHERE work_date='2026-08-09'").fetchone();c.close()

def test_expected_not_covered_is_distinct_and_reconcile_is_quiet(operational):
    path,a,_=operational;c=db.connect(path);safety.create_schedule(c,employee_id=a,effective_from='2026-08-03',effective_to='2026-08-04',weekday_mask='0,1')
    rid=c.execute("INSERT INTO import_runs(source_filename,source_sha256,stored_source_path,status,period_start,period_end)VALUES('fictional.xls','hash','x','applied','2026-08-03','2026-08-04')").lastrowid
    c.execute("INSERT INTO import_run_days(import_run_id,work_date,source_date_present,raw_punch_count,coverage_status)VALUES(?,'2026-08-03',1,0,'reported_zero')",(rid,));c.commit();safety.reconcile(c,'2026-08-03','2026-08-04');events=c.execute("SELECT COUNT(*) FROM exception_events").fetchone()[0];safety.reconcile(c,'2026-08-03','2026-08-04')
    assert c.execute("SELECT COUNT(*) FROM exception_events").fetchone()[0]==events
    assert {r[0] for r in c.execute("SELECT exception_code FROM operational_exceptions WHERE scope='source'")}=={'covered_but_zero_events','expected_period_not_covered'};c.close()

def test_source_quality_drop_stays_source_scoped(operational):
    path,a,b=operational;c=db.connect(path);more=[]
    for index in range(2):more.append(c.execute("INSERT INTO employees(employee_code,name,hire_date,status)VALUES(?,?, '2025-01-01','active')",(f'SAFE-{index+3}',f'가상안전 {index+3}')).lastrowid)
    for employee in [a,b,*more]:safety.create_schedule(c,employee_id=employee,effective_from='2026-08-03',effective_to='2026-08-03',weekday_mask='0')
    rid=c.execute("INSERT INTO import_runs(source_filename,source_sha256,stored_source_path,status)VALUES('fictional.xls','drop-hash','x','applied')").lastrowid
    c.execute("INSERT INTO import_run_days(import_run_id,work_date,source_date_present,raw_punch_count,coverage_status)VALUES(?,'2026-08-03',1,2,'has_punches')",(rid,))
    c.execute("INSERT INTO punch_events(terminal_id,terminal_slot_code,employee_id,punch_at,work_date,punch_type,raw_payload,source_filename,source_sheet,source_row_no,source_column,source_cell,occurrence_index,cell_position,source_hash,dedupe_key,import_run_id,active_import_run_id) VALUES('T','001',?,'2026-08-03T08:00:00','2026-08-03','unknown','{}','fictional.xls','근태기록',1,1,'A1',0,0,'h','d',?,?)",(a,rid,rid))
    c.commit();safety.reconcile(c,'2026-08-03','2026-08-03')
    finding=c.execute("SELECT scope,employee_id FROM operational_exceptions WHERE exception_code='source_quality_drop'").fetchone()
    assert tuple(finding)==('source',None)
    assert not c.execute("SELECT 1 FROM operational_exceptions WHERE exception_code='source_quality_drop' AND employee_id IS NOT NULL").fetchone();c.close()

def test_migration_does_not_promote_unreconstructable_legacy_flag(operational):
    path,a,_=operational;c=db.connect(path);c.execute("INSERT INTO attendance_days(employee_id,work_date,status,review_flag,source)VALUES(?,'2026-08-10','unknown','manual_review','manual')",(a,));c.commit();safety.reconcile(c,'2026-08-10','2026-08-10');assert not c.execute("SELECT 1 FROM operational_exceptions WHERE exception_code='manual_review'").fetchone();c.close()

def test_phase4_to_0008_upgrade_is_additive_and_idempotent(tmp_path):
    migrations=Path(config.MIGRATIONS_DIR);old=tmp_path/'old-migrations';old.mkdir()
    for source in migrations.glob('000[1-7]_*.sql'):(old/source.name).write_bytes(source.read_bytes())
    path=tmp_path/'phase4.db';backups=tmp_path/'backups';migrate.run_migrations(path,migrations_dir=old,backups_dir=backups);c=db.connect(path);c.execute("INSERT INTO employees(employee_code,name,hire_date)VALUES('LEGACY','가상 기존','2025-01-01')");c.commit();c.close()
    result=migrate.run_migrations(path,backups_dir=backups);assert result.applied==[8] and result.backup_path and result.backup_path.exists()
    again=migrate.run_migrations(path,backups_dir=backups);assert not again.applied
    c=db.connect(path);assert c.execute("SELECT COUNT(*) FROM employees").fetchone()[0]==1;assert c.execute("SELECT COUNT(*) FROM operational_exceptions").fetchone()[0]==0;c.close()

def test_http_lifecycle_adjustment_and_overlap(operational,monkeypatch):
    path,a,_=operational;monkeypatch.setattr(config,'DB_PATH',path);client=TestClient(create_app())
    c=db.connect(path);x=safety.ensure_exception(c,code='manual_attendance_review',severity='review',scope='employee',employee_id=a,work_date='2026-08-10',summary='검토');c.commit();c.close()
    assert client.post(f"/api/v1/operations/exceptions/{x['id']}/acknowledge",json={'note':'확인'}).status_code==200
    assert client.post(f"/api/v1/operations/exceptions/{x['id']}/resolve",json={'note':'근거 확인'}).status_code==200
    body={'employeeId':a,'workDate':'2026-08-10','recognizedInAt':'08:00','recognizedOutAt':'16:00','resultingStatus':'normal','reason':'관리자 확인'}
    assert client.post('/api/v1/attendance/manual-adjustments',json=body).status_code==201
    schedule={'effectiveFrom':'2026-08-01','effectiveTo':'2026-08-31','weekdayMask':'0,1,2,3,4'}
    assert client.post(f'/api/v1/employees/{a}/schedules',json=schedule).status_code==201
    assert client.post(f'/api/v1/employees/{a}/schedules',json={**schedule,'effectiveFrom':'2026-08-15'}).status_code==409

def test_schedule_overlap_is_serialized_across_concurrent_requests(operational,monkeypatch):
    path,a,_=operational;monkeypatch.setattr(config,'DB_PATH',path)
    def create(payload):
        with TestClient(create_app()) as client:
            return client.post(f'/api/v1/employees/{a}/schedules',json=payload).status_code
    first={'effectiveFrom':'2026-08-01','effectiveTo':'2026-08-20','weekdayMask':'0,1,2,3,4'}
    second={'effectiveFrom':'2026-08-10','effectiveTo':'2026-08-31','weekdayMask':'0,1,2,3,4'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(create,(first,second)))
    assert sorted(statuses)==[201,409]
    c=db.connect(path);assert c.execute("SELECT COUNT(*) FROM employee_work_schedules WHERE status='active'").fetchone()[0]==1;c.close()

def test_schedule_history_can_be_retired_and_override_cancelled(operational,monkeypatch):
    path,a,_=operational;monkeypatch.setattr(config,'DB_PATH',path);client=TestClient(create_app())
    schedule=client.post(f'/api/v1/employees/{a}/schedules',json={'effectiveFrom':'2026-08-01','effectiveTo':'2026-08-31','weekdayMask':'0,1,2,3,4'}).json()
    override=client.post(f'/api/v1/employees/{a}/schedule-dates',json={'workDate':'2026-08-09','isScheduled':True,'label':'fictional special day'}).json()
    assert client.post(f"/api/v1/employees/{a}/schedules/{schedule['id']}/retire",json={'reason':'schedule corrected'}).status_code==200
    assert client.post(f"/api/v1/employees/{a}/schedule-dates/{override['id']}/cancel",json={'reason':'override corrected'}).status_code==200
    history=client.get(f'/api/v1/employees/{a}/schedules').json()
    assert history['schedules'][0]['status']=='retired' and history['dateOverrides'][0]['status']=='cancelled'
