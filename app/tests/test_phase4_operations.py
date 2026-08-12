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


def test_requested_correction_and_cancel_never_touch_attendance(operational):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-10",end="2026-08-10")
    leave.correct_leave(conn,row["id"],employee_id=a,leave_type="annual_leave",
        start_date="2026-08-11",end_date="2026-08-11",portion="full",reason="date correction")
    leave.cancel_leave(conn,row["id"],"request withdrawn")
    assert conn.execute("SELECT COUNT(*) FROM attendance_days").fetchone()[0]==0
    conn.commit()
    with TestClient(create_app()) as client:
        created=client.post("/api/v1/leave-operations",json={
            "employeeId":a,"leaveType":"annual_leave","startDate":"2026-08-12",
            "endDate":"2026-08-12","portion":"full"}).json()
        assert client.put(f"/api/v1/leave-operations/{created['id']}",json={
            "employeeId":a,"leaveType":"annual_leave","startDate":"2026-08-13",
            "endDate":"2026-08-13","portion":"full","reason":"date correction"}).status_code==200
        assert client.post(f"/api/v1/leave-operations/{created['id']}/cancel",
                           json={"reason":"request withdrawn"}).status_code==200
    assert conn.execute("SELECT COUNT(*) FROM attendance_days").fetchone()[0]==0


def test_approved_employee_date_correction_has_no_cross_employee_phantoms(operational):
    path,a,b,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-10",end="2026-08-10");leave.approve_leave(conn,row["id"])
    leave.correct_leave(conn,row["id"],employee_id=b,leave_type="annual_leave",
        start_date="2026-08-11",end_date="2026-08-11",portion="full",reason="employee correction")
    states={(r["employee_id"],r["work_date"]):r["status"] for r in conn.execute(
        "SELECT employee_id,work_date,status FROM attendance_days")}
    assert states=={(a,"2026-08-10"):"unknown",(b,"2026-08-11"):"leave"}


def _insert_punch(conn,employee,date,key):
    conn.execute("""INSERT INTO punch_events
        (terminal_id,terminal_slot_code,employee_id,punch_at,work_date,punch_type,
         raw_payload,source_filename,source_hash,dedupe_key)
        VALUES('SC-1','001',?,?,?,'unknown','{}','fictional.xls','fictional-hash',?)""",
        (employee,date+"T07:00:00",date,key))


def test_confirmed_attendance_preserved_but_conflict_is_authoritative(operational):
    path,a,_,_=operational;conn=db.connect(path)
    _insert_punch(conn,a,"2026-08-10","confirmed-before")
    conn.execute("""INSERT INTO attendance_days(employee_id,work_date,status,actual_in_at,
        source,review_flag,confirmed_at,confirmed_by)
        VALUES(?,'2026-08-10','late','2026-08-10T07:00:00','fingerprint',
               'manual_review','2026-08-12T00:00:00.000Z','operator')""",(a,))
    before=dict(conn.execute("SELECT * FROM attendance_days").fetchone())
    row=create(conn,a,start="2026-08-10",end="2026-08-10");leave.approve_leave(conn,row["id"])
    after=dict(conn.execute("SELECT * FROM attendance_days").fetchone())
    assert after==before
    assert leave.list_leave(conn,month_start="2026-08-01",month_end="2026-08-31")[0]["finding"]=="leave_attendance_conflict"
    view=__import__("app.services.ops",fromlist=["week_view"]).week_view(conn,"2026-08-10","2026-08-10")
    employee=view["employees"][0]
    assert employee["cells"][0]["issue"] is True


def test_import_after_confirmed_leave_surfaces_conflict_without_overwrite(operational,tmp_path):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-10",end="2026-08-10");leave.approve_leave(conn,row["id"])
    conn.execute("UPDATE attendance_days SET status='late',review_flag='manual_review',confirmed_at='2026-08-12T00:00:00.000Z' WHERE employee_id=?",(a,))
    before=dict(conn.execute("SELECT * FROM attendance_days").fetchone())
    conn.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('001',?,'2026-01-01','mapped')",(a,));conn.commit();conn.close()
    source=build_export(tmp_path/"confirmed.xls",year=2026,month=8,slots=[SlotSpec("001","Fictional",{10:["07:00","16:00"]})])
    p=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"up")
    xls_pipeline.apply_import(p.import_run_id,p.confirmation_token,db_path=path,backups_dir=tmp_path/"back")
    conn=db.connect(path);after=dict(conn.execute("SELECT * FROM attendance_days").fetchone())
    assert after==before
    assert leave.list_leave(conn)[0]["finding"]=="leave_attendance_conflict"


def test_rollback_leave_conflict_clears_fingerprint_times_and_owner(operational,tmp_path):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-10",end="2026-08-10");leave.approve_leave(conn,row["id"])
    conn.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('001',?,'2026-01-01','mapped')",(a,));conn.commit();conn.close()
    source=build_export(tmp_path/"rollback.xls",year=2026,month=8,slots=[SlotSpec("001","Fictional",{10:["07:00","16:00"]})])
    p=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"up")
    xls_pipeline.apply_import(p.import_run_id,p.confirmation_token,db_path=path,backups_dir=tmp_path/"back")
    xls_pipeline.rollback_import(p.import_run_id,"mapping correction",db_path=path)
    conn=db.connect(path);attendance=conn.execute("""SELECT status,actual_in_at,actual_out_at,
        source,review_flag,last_import_run_id FROM attendance_days""").fetchone()
    assert tuple(attendance)==("leave",None,None,"manual",None,None)
    assert conn.execute("SELECT COUNT(*) FROM punch_events WHERE rolled_back_at IS NULL").fetchone()[0]==0
    leave.cancel_leave(conn,row["id"],"leave cancelled")
    attendance=conn.execute("SELECT actual_in_at,actual_out_at,status FROM attendance_days").fetchone()
    assert tuple(attendance)==(None,None,"unknown")


def test_replacement_status_lifecycle_patch_and_link_validation(operational):
    path,a,b,_=operational;conn=db.connect(path)
    assignment=repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=b,
        start_date="2026-08-10",end_date="2026-08-10",zone="Site A")
    repl.set_status(conn,assignment["id"],"confirmed");repl.set_status(conn,assignment["id"],"completed")
    with pytest.raises(repl.ReplacementError):repl.set_status(conn,assignment["id"],"planned")
    with pytest.raises(repl.ReplacementError):repl.update_assignment(conn,assignment["id"],{"zone":"Site B"})
    cancelled=repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=b,
        start_date="2026-08-11",end_date="2026-08-11",zone="Site A")
    repl.set_status(conn,cancelled["id"],"cancelled")
    with pytest.raises(repl.ReplacementError):repl.set_status(conn,cancelled["id"],"confirmed")
    with TestClient(create_app()) as client:
        assert client.post(f"/api/v1/replacement-operations/{assignment['id']}/status",
                           json={"status":"planned"}).status_code==409
        assert client.patch(f"/api/v1/replacement-operations/{assignment['id']}",
                            json={"status":"planned"}).status_code==409


def test_month_overlap_filters_and_multiday_replacement_stats(operational):
    path,a,b,_=operational;conn=db.connect(path)
    create(conn,a,start="2026-08-31",end="2026-09-02")
    repl_row=repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=b,
        start_date="2026-08-10",end_date="2026-08-12",zone="Site A")
    repl.set_status(conn,repl_row["id"],"confirmed")
    conn.commit()
    with TestClient(create_app()) as client:
        assert len(client.get("/api/v1/leave-operations?month=2026-08").json()["leaves"])==1
        assert len(client.get("/api/v1/leave-operations?month=2026-09").json()["leaves"])==1
        assert client.get("/api/v1/leave-operations?month=2026-09").json()["balanceYear"]==2026
    from app.services import ops
    stats=ops.month_stats(conn,2026,8)
    assert [stats[str(day)]["replace"] for day in (10,11,12)]==[1,1,1]
    week=ops.week_view(conn,"2026-08-10","2026-08-10")
    worker=week["employees"][1]
    assert [cell["type"] for cell in worker["cells"][:3]]==["replacement"]*3


@pytest.mark.parametrize("date,is_working,expected",[
    ("2026-08-08",None,False),
    ("2026-08-10",False,False),
    ("2026-08-08",True,True),
])
def test_leave_punch_conflict_respects_work_calendar(operational,date,is_working,expected):
    path,a,_,_=operational;conn=db.connect(path)
    if is_working is not None:
        conn.execute("INSERT INTO site_calendar(calendar_date,day_type,is_working) VALUES(?,?,?)",(date,"special",is_working))
    row=create(conn,a,start="2026-08-07",end="2026-08-10");leave.approve_leave(conn,row["id"])
    _insert_punch(conn,a,date,"calendar-"+date)
    item=leave.list_leave(conn)[0]
    assert ("leave_attendance_conflict" in item["findings"]) is expected
    from app.services import ops
    view=ops.week_view(conn,"2026-08-07","2026-08-07")
    cell=view["employees"][0]["cells"][(int(date[-2:])-7)]
    assert (cell.get("issue") is True) is expected


def test_approved_am_pm_aggregate_to_full_day(operational):
    path,a,_,_=operational;conn=db.connect(path)
    am=create(conn,a,"half_day","2026-08-10","2026-08-10","am")
    pm=create(conn,a,"half_day","2026-08-10","2026-08-10","pm")
    leave.approve_leave(conn,am["id"]);leave.approve_leave(conn,pm["id"])
    assert leave.balance(conn,a,2026)["used"]==1.0
    assert leave.approved_leave_coverage(conn,a,"2026-08-10")["coverage"]=="full"
    assert tuple(conn.execute("SELECT status,review_flag FROM attendance_days").fetchone())==("leave",None)
    _insert_punch(conn,a,"2026-08-10","both-halves")
    leave._sync_attendance(conn,a,{"2026-08-10"})
    assert tuple(conn.execute("SELECT status,review_flag FROM attendance_days").fetchone())==("leave","leave_attendance_conflict")


def test_sick_mismatch_and_punch_preserve_both_findings(operational):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,"sick_leave","2026-08-04","2026-09-11",evidence_received=True,
        evidence_start_date="2026-08-04",evidence_end_date="2026-08-31")
    leave.approve_leave(conn,row["id"])
    assert leave.list_leave(conn)[0]["findings"]==["sick_leave_evidence_mismatch"]
    _insert_punch(conn,a,"2026-08-04","sick-both")
    findings=leave.list_leave(conn)[0]["findings"]
    assert findings==["sick_leave_evidence_mismatch","leave_attendance_conflict"]


def test_replacement_edit_revalidates_link_and_allows_null_absent(operational):
    path,a,b,_=operational;conn=db.connect(path)
    other=conn.execute("INSERT INTO employees(employee_code,name,hire_date,status) VALUES('P4-D','Fictional D','2020-01-01','active')").lastrowid
    linked=create(conn,a,start="2026-08-10",end="2026-08-12")
    assignment=repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=b,
        start_date="2026-08-10",end_date="2026-08-12",zone="A",leave_request_id=linked["id"])
    with pytest.raises(repl.ReplacementError,match="belong"):
        repl.update_assignment(conn,assignment["id"],{"absentEmployeeId":other})
    with pytest.raises(repl.ReplacementError,match="covered"):
        repl.update_assignment(conn,assignment["id"],{"startDate":"2026-08-15","endDate":"2026-08-15"})
    loose=repl.create_assignment(conn,absent_employee_id=None,replacement_employee_id=b,
        start_date="2026-08-13",end_date="2026-08-13",zone="A")
    changed=repl.update_assignment(conn,loose["id"],{"zone":"B","note":"fictional"})
    assert changed["absentEmployeeId"] is None and changed["zone"]=="B"
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='replacement.update'").fetchone()[0]==1


@pytest.mark.parametrize("payload",[
    {"leaveType":"annual_leave","startDate":"2026-08-11","endDate":"2026-08-10","portion":"full"},
    {"leaveType":"half_day","startDate":"2026-08-10","endDate":"2026-08-11","portion":"am"},
])
def test_bad_leave_calendar_inputs_are_controlled_http_errors(operational,payload):
    path,a,_,_=operational
    payload={"employeeId":a,**payload}
    with TestClient(create_app()) as client:
        response=client.post("/api/v1/leave-operations",json=payload)
    assert response.status_code in {409,422}
    assert db.connect(path).execute("SELECT COUNT(*) FROM leave_requests").fetchone()[0]==0


def test_operational_ui_initial_month_is_dynamic():
    script=Path("phase4-ui.js").read_text(encoding="utf-8")
    assert "selectedMonth='2026-08'" not in script
    assert "now.getFullYear()" in script and "now.getMonth()+1" in script


def test_xls_derivation_uses_authoritative_work_calendar(operational,tmp_path):
    path,a,_,_=operational;conn=db.connect(path)
    conn.execute("INSERT INTO site_calendar(calendar_date,day_type,is_working) VALUES('2026-08-08','special',1)")
    conn.execute("INSERT INTO site_calendar(calendar_date,day_type,is_working) VALUES('2026-08-10','holiday',0)")
    row=create(conn,a,start="2026-08-07",end="2026-08-10");leave.approve_leave(conn,row["id"])
    conn.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('001',?,'2026-01-01','mapped')",(a,));conn.commit();conn.close()
    source=build_export(tmp_path/"calendar.xls",year=2026,month=8,slots=[SlotSpec("001","Fictional",{
        8:["07:00","16:00"],10:["07:00","16:00"]})])
    preview=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"up")
    xls_pipeline.apply_import(preview.import_run_id,preview.confirmation_token,db_path=path,backups_dir=tmp_path/"back")
    conn=db.connect(path)
    rows={r["work_date"]:dict(r) for r in conn.execute("SELECT work_date,status,review_flag FROM attendance_days WHERE work_date IN ('2026-08-08','2026-08-10')")}
    assert rows["2026-08-08"]["review_flag"]=="leave_attendance_conflict"
    assert rows["2026-08-10"]["status"]=="normal" and rows["2026-08-10"]["review_flag"] is None
