from pathlib import Path
import shutil
import pytest
from fastapi.testclient import TestClient

from app import config, db, migrate
from app.main import create_app
from app.services import leave_operations as leave, replacement_operations as repl, xls_pipeline
from app.tests.fixtures.terminal_xls import SlotSpec, build_export


@pytest.fixture
def operational(monkeypatch,migrated_db,tmp_path):
    conn=db.connect(migrated_db)
    conn.execute("INSERT INTO app_meta(key,value) VALUES('data_context','operational') ON CONFLICT(key) DO UPDATE SET value='operational'")
    a=conn.execute("INSERT INTO employees(employee_code,name,zone,hire_date,status) VALUES('P4-A','가상 직원 A','본관','2020-01-01','active')").lastrowid
    b=conn.execute("INSERT INTO employees(employee_code,name,zone,hire_date,status) VALUES('P4-B','가상 직원 B','별관','2020-01-01','active')").lastrowid
    c=conn.execute("INSERT INTO employees(employee_code,name,zone,hire_date,end_date,status) VALUES('P4-C','가상 직원 C','별관','2020-01-01','2026-07-31','terminated')").lastrowid
    conn.execute("INSERT INTO leave_balances(employee_id,leave_year,granted_days) VALUES(?,?,15)",(a,2026))
    conn.execute("INSERT INTO leave_balances(employee_id,leave_year,granted_days) VALUES(?,?,16)",(a,2027))
    conn.commit();conn.close()
    monkeypatch.setattr(config,"DB_PATH",migrated_db);monkeypatch.setattr(config,"UPLOADS_DIR",tmp_path/"uploads");monkeypatch.setattr(config,"BACKUPS_DIR",tmp_path/"backups");monkeypatch.setattr(config,"ALLOW_DEMO_IMPORT",False)
    return migrated_db,a,b,c


def create(conn,employee_id,leave_type="annual_leave",start="2026-08-07",end="2026-08-10",portion="full",**kw):
    return leave.create_leave(conn,employee_id=employee_id,leave_type=leave_type,start_date=start,end_date=end,portion=portion,**kw)


def test_work_calendar_weekend_and_site_holiday_are_excluded(operational):
    path,a,_,_=operational;conn=db.connect(path)
    friday_monday=create(conn,a)
    assert friday_monday["calculatedDays"]==2.0
    conn.execute("INSERT INTO site_calendar(calendar_date,day_type,is_working,label) VALUES('2026-08-10','holiday',0,'가상 휴일')")
    tuesday=create(conn,a,start="2026-08-11",end="2026-08-11")
    assert tuesday["calculatedDays"]==1.0


def test_site_holiday_inside_period_is_excluded(operational):
    path,a,_,_=operational;conn=db.connect(path)
    conn.execute("INSERT INTO site_calendar(calendar_date,day_type,is_working) VALUES('2026-08-11','holiday',0)")
    row=create(conn,a,start="2026-08-10",end="2026-08-12")
    assert row["calculatedDays"]==2.0


def test_year_specific_balance_half_day_approval_and_cancel(operational):
    path,a,_,_=operational;conn=db.connect(path)
    half=create(conn,a,"half_day","2026-08-10","2026-08-10","am")
    assert half["calculatedDays"]==0.5
    leave.approve_leave(conn,half["id"])
    assert leave.balance(conn,a,2026)=={"employeeId":a,"year":2026,"entitlement":15.0,"used":0.5,"remaining":14.5}
    assert leave.balance(conn,a,2027)["remaining"]==16.0
    leave.cancel_leave(conn,half["id"],"일정 변경")
    assert leave.balance(conn,a,2026)["used"]==0


def test_requested_cancelled_and_rejected_do_not_consume_balance(operational):
    path,a,_,_=operational;conn=db.connect(path)
    requested=create(conn,a,start="2026-08-10",end="2026-08-10")
    assert leave.balance(conn,a,2026)["used"]==0
    leave.cancel_leave(conn,requested["id"],"취소")
    rejected=create(conn,a,start="2026-08-11",end="2026-08-11")
    conn.execute("UPDATE leave_requests SET status='rejected' WHERE id=?",(rejected["id"],))
    assert leave.balance(conn,a,2026)["used"]==0


def test_leave_overlap_rules_full_and_partial(operational):
    path,a,_,_=operational;conn=db.connect(path)
    create(conn,a,start="2026-08-10",end="2026-08-12")
    with pytest.raises(leave.LeaveError):create(conn,a,"sick_leave","2026-08-12","2026-08-13")
    with pytest.raises(leave.LeaveError):create(conn,a,"half_day","2026-08-10","2026-08-10","am")
    conn.execute("UPDATE leave_requests SET status='cancelled'")
    create(conn,a,"half_day","2026-08-10","2026-08-10","am")
    with pytest.raises(leave.LeaveError):create(conn,a,"half_day","2026-08-10","2026-08-10","am")
    pm=create(conn,a,"half_day","2026-08-10","2026-08-10","pm")
    assert pm["calculatedDays"]==0.5


def test_employment_date_validation(operational):
    path,a,_,c=operational;conn=db.connect(path)
    conn.execute("UPDATE employees SET hire_date='2026-08-05' WHERE id=?",(a,))
    with pytest.raises(leave.LeaveError,match="입사일"):create(conn,a,start="2026-08-04",end="2026-08-04")
    with pytest.raises(leave.LeaveError,match="퇴사일"):create(conn,c,start="2026-08-01",end="2026-08-01")


def test_sick_evidence_mismatch_preserves_both_periods(operational):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,"sick_leave","2026-08-04","2026-09-11",evidence_received=True,evidence_start_date="2026-08-04",evidence_end_date="2026-08-31",evidence_note="가상 증빙 확인")
    assert (row["startDate"],row["endDate"],row["evidenceStartDate"],row["evidenceEndDate"])==("2026-08-04","2026-09-11","2026-08-04","2026-08-31")
    assert row["finding"]=="sick_leave_evidence_mismatch"


def test_approved_leave_attendance_rules_never_invent_absence(operational,tmp_path):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-03",end="2026-08-03");leave.approve_leave(conn,row["id"])
    assert conn.execute("SELECT status FROM attendance_days WHERE employee_id=? AND work_date='2026-08-03'",(a,)).fetchone()[0]=="leave"
    conn.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('001',?,'2026-01-01','mapped')",(a,));conn.commit();conn.close()
    source=build_export(tmp_path/"conflict.xls",year=2026,month=8,slots=[SlotSpec("001","가상 슬롯",{3:["07:00","16:00"]})])
    preview=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads")
    xls_pipeline.apply_import(preview.import_run_id,preview.confirmation_token,db_path=path,backups_dir=tmp_path/"backups")
    conn=db.connect(path);attendance=conn.execute("SELECT status,review_flag FROM attendance_days WHERE employee_id=? AND work_date='2026-08-03'",(a,)).fetchone()
    assert tuple(attendance)==("leave","leave_attendance_conflict")
    assert conn.execute("SELECT COUNT(*) FROM attendance_days WHERE status='absent'").fetchone()[0]==0


def test_half_day_with_punches_is_review_not_conflict(operational,tmp_path):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,"half_day","2026-08-03","2026-08-03","am");leave.approve_leave(conn,row["id"])
    conn.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('001',?,'2026-01-01','mapped')",(a,));conn.commit();conn.close()
    source=build_export(tmp_path/"half.xls",year=2026,month=8,slots=[SlotSpec("001","가상 슬롯",{3:["12:30","16:00"]})])
    p=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"up");xls_pipeline.apply_import(p.import_run_id,p.confirmation_token,db_path=path,backups_dir=tmp_path/"back")
    conn=db.connect(path);assert conn.execute("SELECT review_flag FROM attendance_days WHERE employee_id=? AND work_date='2026-08-03'",(a,)).fetchone()[0]=="partial_leave_review"


def test_leave_correction_preserves_identity_and_audits(operational):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-10",end="2026-08-10")
    corrected=leave.correct_leave(conn,row["id"],employee_id=a,leave_type="annual_leave",start_date="2026-08-11",end_date="2026-08-11",portion="full",reason="날짜 오류")
    assert corrected["id"]==row["id"]
    assert [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE entity_type='leave_requests' ORDER BY id")]==["leave.create","leave.correct"]


def test_replacement_overlap_inactive_and_checklist_patch(operational):
    path,a,b,c=operational;conn=db.connect(path)
    first=repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=b,start_date="2026-08-10",end_date="2026-08-12",zone="본관")
    with pytest.raises(repl.ReplacementError,match="이미 배정"):repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=b,start_date="2026-08-12",end_date="2026-08-13",zone="별관")
    with pytest.raises(repl.ReplacementError,match="비재직"):repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=c,start_date="2026-08-10",end_date="2026-08-10",zone="본관")
    repl.patch_checklist(conn,first["id"],{"keyReceived":True,"uniformReady":True})
    patched=repl.patch_checklist(conn,first["id"],{"orientationDone":True})
    assert patched["checklist"]=={"keyReceived":True,"uniformReady":True,"orientationDone":True}


def test_phase4_http_workflow_and_demo_refusal(operational):
    path,a,b,_=operational
    with TestClient(create_app()) as client:
        created=client.post("/api/v1/leave-operations",json={"employeeId":a,"leaveType":"annual_leave","startDate":"2026-08-10","endDate":"2026-08-10","portion":"full"})
        assert created.status_code==201
        assert client.post(f"/api/v1/leave-operations/{created.json()['id']}/approve").status_code==200
        assignment=client.post("/api/v1/replacement-operations",json={"absentEmployeeId":a,"replacementEmployeeId":b,"startDate":"2026-08-10","endDate":"2026-08-10","zone":"본관"})
        assert assignment.status_code==201
        patched=client.patch(f"/api/v1/replacement-operations/{assignment.json()['id']}/checklist",json={"orientationDone":True})
        assert patched.json()["checklist"]["orientationDone"] is True
    conn=db.connect(path);conn.execute("UPDATE app_meta SET value='demo' WHERE key='data_context'");conn.commit();conn.close()
    with TestClient(create_app()) as client:
        assert client.post("/api/v1/leave-operations",json={"employeeId":a,"leaveType":"annual_leave","startDate":"2026-08-11","endDate":"2026-08-11"}).status_code==409


def test_phase4_frontend_demo_guards_all_mutations():
    script=Path("phase4-ui.js").read_text(encoding="utf-8")
    assert "if(demo())return Promise.reject" in script
    assert "function init(){if(demo())return" in script
    assert "fetch(url,opt)" in script


def test_cross_year_leave_is_explicitly_split(operational):
    path,a,_,_=operational;conn=db.connect(path)
    with pytest.raises(leave.LeaveError, match="cross-year"):
        create(conn,a,start="2026-12-31",end="2027-01-04")


def test_leave_change_preserves_confirmed_attendance_and_restores_incomplete_flag(operational):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-10",end="2026-08-10")
    leave.approve_leave(conn,row["id"])
    conn.execute(
        "UPDATE attendance_days SET status='late',review_flag='manual_review',"
        "confirmed_at='2026-08-12T00:00:00.000Z' WHERE employee_id=? AND work_date='2026-08-10'",
        (a,),
    )
    leave.cancel_leave(conn,row["id"],"operator correction")
    assert tuple(conn.execute(
        "SELECT status,review_flag FROM attendance_days WHERE employee_id=? AND work_date='2026-08-10'",
        (a,),
    ).fetchone())==("late","manual_review")

    one=create(conn,a,start="2026-08-11",end="2026-08-11")
    leave.approve_leave(conn,one["id"])
    conn.execute(
        """INSERT INTO punch_events
           (terminal_id,terminal_slot_code,employee_id,punch_at,work_date,punch_type,
            raw_payload,source_filename,source_hash,dedupe_key)
           VALUES('SC-1','001',?,'2026-08-11T08:00:00','2026-08-11','unknown',
                  '{}','fictional.xls','hash-one','dedupe-one')""",
        (a,),
    )
    leave.cancel_leave(conn,one["id"],"operator correction")
    assert tuple(conn.execute(
        "SELECT status,review_flag FROM attendance_days WHERE employee_id=? AND work_date='2026-08-11'",
        (a,),
    ).fetchone())==("unknown","incomplete_day")


def test_0007_upgrades_phase35_data_with_backup_and_no_loss(tmp_path):
    migrations=Path("app/migrations")
    earlier=tmp_path/"migrations-v6";earlier.mkdir()
    for source in sorted(migrations.glob("*.sql")):
        if source.name.startswith("0007_"): continue
        shutil.copy2(source,earlier/source.name)
    database=tmp_path/"upgrade.db";backups=tmp_path/"backups"
    assert migrate.run_migrations(database,earlier,backups).schema_version==6
    conn=db.connect(database)
    employee=conn.execute(
        "INSERT INTO employees(employee_code,name,hire_date) VALUES('OLD-1','Fictional Existing','2020-01-01')"
    ).lastrowid
    assignment=conn.execute(
        """INSERT INTO replacement_assignments
           (work_date,shift,zone,substitute_employee_id,status)
           VALUES('2026-08-10','day','Site A',?,'assigned')""",(employee,)
    ).lastrowid
    conn.commit();conn.close()
    result=migrate.run_migrations(database,backups_dir=backups)
    assert result.applied==[7] and result.backup_path and result.backup_path.exists()
    conn=db.connect(database)
    upgraded=conn.execute(
        "SELECT work_date,start_date,end_date,key_received FROM replacement_assignments WHERE id=?",
        (assignment,),
    ).fetchone()
    assert tuple(upgraded)==("2026-08-10","2026-08-10","2026-08-10",0)
    assert migrate.run_migrations(database,backups_dir=backups).applied==[]
