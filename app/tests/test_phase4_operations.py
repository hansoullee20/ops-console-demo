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
    a=conn.execute("INSERT INTO employees(employee_code,name,zone,hire_date,status) VALUES('P4-A','ê°€ìƒ ì§ì› A','ë³¸ê´€','2020-01-01','active')").lastrowid
    b=conn.execute("INSERT INTO employees(employee_code,name,zone,hire_date,status) VALUES('P4-B','ê°€ìƒ ì§ì› B','ë³„ê´€','2020-01-01','active')").lastrowid
    c=conn.execute("INSERT INTO employees(employee_code,name,zone,hire_date,end_date,status) VALUES('P4-C','ê°€ìƒ ì§ì› C','ë³„ê´€','2020-01-01','2026-07-31','terminated')").lastrowid
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
    conn.execute("INSERT INTO site_calendar(calendar_date,day_type,is_working,label) VALUES('2026-08-10','holiday',0,'ê°€ìƒ íœ´ì¼')")
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
    leave.cancel_leave(conn,half["id"],"ì¼ì • ë³€ê²½")
    assert leave.balance(conn,a,2026)["used"]==0


def test_requested_cancelled_and_rejected_do_not_consume_balance(operational):
    path,a,_,_=operational;conn=db.connect(path)
    requested=create(conn,a,start="2026-08-10",end="2026-08-10")
    assert leave.balance(conn,a,2026)["used"]==0
    leave.cancel_leave(conn,requested["id"],"ì·¨ì†Œ")
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
    with pytest.raises(leave.LeaveError,match="ì…ì‚¬ì¼"):create(conn,a,start="2026-08-04",end="2026-08-04")
    with pytest.raises(leave.LeaveError,match="í‡´ì‚¬ì¼"):create(conn,c,start="2026-08-01",end="2026-08-01")


def test_sick_evidence_mismatch_preserves_both_periods(operational):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,"sick_leave","2026-08-04","2026-09-11",evidence_received=True,evidence_start_date="2026-08-04",evidence_end_date="2026-08-31",evidence_note="ê°€ìƒ ì¦ë¹™ í™•ì¸")
    assert (row["startDate"],row["endDate"],row["evidenceStartDate"],row["evidenceEndDate"])==("2026-08-04","2026-09-11","2026-08-04","2026-08-31")
    assert row["finding"]=="sick_leave_evidence_mismatch"


def test_approved_leave_attendance_rules_never_invent_absence(operational,tmp_path):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-03",end="2026-08-03");leave.approve_leave(conn,row["id"])
    assert conn.execute("SELECT status FROM attendance_days WHERE employee_id=? AND work_date='2026-08-03'",(a,)).fetchone()[0]=="leave"
    conn.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('001',?,'2026-01-01','mapped')",(a,));conn.commit();conn.close()
    source=build_export(tmp_path/"conflict.xls",year=2026,month=8,slots=[SlotSpec("001","ê°€ìƒ ìŠ¬ë¡¯",{3:["07:00","16:00"]})])
    preview=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"uploads")
    xls_pipeline.apply_import(preview.import_run_id,preview.confirmation_token,db_path=path,backups_dir=tmp_path/"backups")
    conn=db.connect(path);attendance=conn.execute("SELECT status,review_flag FROM attendance_days WHERE employee_id=? AND work_date='2026-08-03'",(a,)).fetchone()
    assert tuple(attendance)==("leave","leave_attendance_conflict")
    assert conn.execute("SELECT COUNT(*) FROM attendance_days WHERE status='absent'").fetchone()[0]==0


def test_half_day_with_punches_is_review_not_conflict(operational,tmp_path):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,"half_day","2026-08-03","2026-08-03","am");leave.approve_leave(conn,row["id"])
    conn.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('001',?,'2026-01-01','mapped')",(a,));conn.commit();conn.close()
    source=build_export(tmp_path/"half.xls",year=2026,month=8,slots=[SlotSpec("001","ê°€ìƒ ìŠ¬ë¡¯",{3:["12:30","16:00"]})])
    p=xls_pipeline.preview_import(source,db_path=path,uploads_dir=tmp_path/"up");xls_pipeline.apply_import(p.import_run_id,p.confirmation_token,db_path=path,backups_dir=tmp_path/"back")
    conn=db.connect(path);assert conn.execute("SELECT review_flag FROM attendance_days WHERE employee_id=? AND work_date='2026-08-03'",(a,)).fetchone()[0]=="partial_leave_review"


def test_leave_correction_preserves_identity_and_audits(operational):
    path,a,_,_=operational;conn=db.connect(path)
    row=create(conn,a,start="2026-08-10",end="2026-08-10")
    corrected=leave.correct_leave(conn,row["id"],employee_id=a,leave_type="annual_leave",start_date="2026-08-11",end_date="2026-08-11",portion="full",reason="ë‚ ì§œ ì˜¤ë¥˜")
    assert corrected["id"]==row["id"]
    assert [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE entity_type='leave_requests' ORDER BY id")]==["leave.create","leave.correct"]


def test_replacement_overlap_inactive_and_checklist_patch(operational):
    path,a,b,c=operational;conn=db.connect(path)
    first=repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=b,start_date="2026-08-10",end_date="2026-08-12",zone="ë³¸ê´€")
    with pytest.raises(repl.ReplacementError,match="ì´ë¯¸ ë°°ì •"):repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=b,start_date="2026-08-12",end_date="2026-08-13",zone="ë³„ê´€")
    with pytest.raises(repl.ReplacementError,match="ë¹„ì¬ì§"):repl.create_assignment(conn,absent_employee_id=a,replacement_employee_id=c,start_date="2026-08-10",end_date="2026-08-10",zone="ë³¸ê´€")
    repl.patch_checklist(conn,first["id"],{"keyReceived":True,"uniformReady":True})
    patched=repl.patch_checklist(conn,first["id"],{"orientationDone":True})
    assert patched["checklist"]=={"keyReceived":True,"uniformReady":True,"orientationDone":True}


def test_phase4_http_workflow_and_demo_refusal(operational):
    path,a,b,_=operational
    with TestClient(create_app()) as client:
        created=client.post("/api/v1/leave-operations",json={"employeeId":a,"leaveType":"annual_leave","startDate":"2026-08-10","endDate":"2026-08-10","portion":"full"})
        assert created.status_code==201
        assert client.post(f"/api/v1/leave-operations/{created.json()['id']}/approve").status_code==200
        assignment=client.post("/api/v1/replacement-operations",json={"absentEmployeeId":a,"replacementEmployeeId":b,"startDate":"2026-08-10","endDate":"2026-08-10","zone":"ë³¸ê´€"})
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
        if source.name.startswith(("0007_", "0008_")): continue
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
    assert result.applied==[7,8] and result.backup_path and result.backup_path.exists()
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
        start_date="2026-08-11",eïËh‘éì¶»§q«^tÏO^ÊKŒŒ‹LLLŠNˆ[šÛ›İÛˆ‹
‹ŒŒ‹LLLHŠNˆ›X]™HŸB‚‚™YˆÚ[œÙ\Ü[˜Ú
ÛÛ›‹[\ŞYYK]KÙ^JN‚ˆÛÛ›‹™^Xİ]Jˆˆ’S”ÑT•S•È[˜ÚÙ]™[Âˆ
\›Z[˜[ÚY\›Z[˜[ÜÛİØÛÙK[\ŞYYWÚY[˜ÚØ]ÛÜš×Ù]K[˜Úİ\Kˆ˜]×Ü^[ØYÛİ\˜ÙWÙš[[˜[YKÛİ\˜ÙWÚ\ÚY\WÚÙ^JBˆSQTÊ	ÔĞËLIË	ÌIËËËË	İ[šÛ›İÛ‰Ë	ŞßIË	ÙšXİ[Û˜[ÉË	ÙšXİ[Û˜[Z\Ú	ËÊHˆˆ‹ˆ
[\ŞYYK]JÈ•ÎŒŒ‹]KÙ^JJB‚‚™Yˆ\İØÛÛ™š\›YYØ][™[˜ÙWÜ™\Ù\™YØ]ØÛÛ™›XİÚ\×Ø]]Üš]]]™JÜ\˜][Û˜[
N‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
BˆÚ[œÙ\Ü[˜Ú
ÛÛ›‹KŒŒ‹LLL‹˜ÛÛ™š\›YYX™Y›Ü™HŠBˆÛÛ›‹™^Xİ]Jˆˆ’S”ÑT•S•È][™[˜ÙWÙ^\Ê[\ŞYYWÚYÛÜš×Ù]Kİ]\ËXİX[Ú[—Ø]ˆÛİ\˜ÙK™]šY]×Ù›YËÛÛ™š\›YYØ]ÛÛ™š\›YYØJBˆSQTÊË	ÌŒ‹LLL	Ë	Û]IË	ÌŒ‹LLLÎŒŒ	Ë	Ùš[™Ù\œš[	Ëˆ	ÛX[X[Ü™]šY]ÉË	ÌŒ‹LLL•ŒŒŒ‰Ë	ÛÜ\˜]Ü‰ÊHˆˆ‹
K
JBˆ™Y›Ü™OYXİ
ÛÛ›‹™^Xİ]J”ÑSPÕ
ˆ”“ÓH][™[˜ÙWÙ^\ÈŠK™™]ÚÛ™J
JBˆ›İÏXÜ™X]JÛÛ›‹Kİ\HŒŒ‹LLL‹[™HŒŒ‹LLLŠNÛX]™K˜\›İ™WÛX]™JÛÛ›‹›İÖÈšY—JBˆY\YXİ
ÛÛ›‹™^Xİ]J”ÑSPÕ
ˆ”“ÓH][™[˜ÙWÙ^\ÈŠK™™]ÚÛ™J
JBˆ\ÜÙ\Y\OX™Y›Ü™Bˆ\ÜÙ\X]™K›\İÛX]™JÛÛ›‹[ÛÜİ\HŒŒ‹LLH‹[ÛÙ[™HŒŒ‹LLÌHŠVÌVÈ™š[™[™È—OOH›X]™WØ][™[˜ÙWØÛÛ™›Xİ‚ˆšY]ÏW×Ú[\Ü×Ê˜\œÙ\šXÙ\Ë›ÜÈ‹œ›Û[\İVÈÙYZ×İšY]È—JKÙYZ×İšY]ÊÛÛ›‹ŒŒ‹LLL‹ŒŒ‹LLLŠBˆ[\ŞYYO]šY]ÖÈ™[\ŞYY\È—VÌBˆ\ÜÙ\[\ŞYYVÈ˜Ù[È—VÌVÈš\ÜİYH—H\ÈYB‚‚™Yˆ\İÚ[\ÜØY\—ØÛÛ™š\›YYÛX]™WÜİ\™˜XÙ\×ØÛÛ™›XİİÚ]İ]Ûİ™\Üš]JÜ\˜][Û˜[\Ü]
N‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
Bˆ›İÏXÜ™X]JÛÛ›‹Kİ\HŒŒ‹LLL‹[™HŒŒ‹LLLŠNÛX]™K˜\›İ™WÛX]™JÛÛ›‹›İÖÈšY—JBˆÛÛ›‹™^Xİ]J•TUH][™[˜ÙWÙ^\ÈÑUİ]\ÏIÛ]IË™]šY]×Ù›YÏIÛX[X[Ü™]šY]ÉËÛÛ™š\›YYØ]IÌŒ‹LLL•ŒŒŒ‰ÈÒT‘H[\ŞYYWÚYOÈ‹
K
JBˆ™Y›Ü™OYXİ
ÛÛ›‹™^Xİ]J”ÑSPÕ
ˆ”“ÓH][™[˜ÙWÙ^\ÈŠK™™]ÚÛ™J
JBˆÛÛ›‹™^Xİ]J’S”ÑT•S•È\›Z[˜[ÜÛİÊÛİØÛÙK[\ŞYYWÚYY™™Xİ]™WÙœ›ÛKİ]\ÊHSQTÊ	ÌIËË	ÌŒ‹LKLIË	ÛX\Y	ÊH‹
K
JNØÛÛ›‹˜ÛÛ[Z]

NØÛÛ›‹˜ÛÜÙJ
BˆÛİ\˜ÙOXZ[Ù^Ü
\Ü]È˜ÛÛ™š\›YYÈ‹YX\LŒ‹[ÛNÛİÏVÔÛİÜXÊŒH‹‘šXİ[Û˜[‹ÌL–ÈŒÎŒ‹ŒMŒ—_JWJBˆ^×Ü\[[™Kœ™]šY]×Ú[\Ü
Ûİ\˜ÙK—Ü]\]\ØY×Ù\]\Ü]È\ŠBˆ×Ü\[[™K˜\WÚ[\Ü
š[\ÜÜ[—ÚY˜ÛÛ™š\›X][Û—İÚÙ[‹—Ü]\]˜XÚİ\×Ù\]\Ü]È˜˜XÚÈŠBˆÛÛ›Y‹˜ÛÛ›™Xİ
]
NØY\YXİ
ÛÛ›‹™^Xİ]J”ÑSPÕ
ˆ”“ÓH][™[˜ÙWÙ^\ÈŠK™™]ÚÛ™J
JBˆ\ÜÙ\Y\OX™Y›Ü™Bˆ\ÜÙ\X]™K›\İÛX]™JÛÛ›ŠVÌVÈ™š[™[™È—OOH›X]™WØ][™[˜ÙWØÛÛ™›Xİ‚‚‚™Yˆ\İÜ›Û˜XÚ×ÛX]™WØÛÛ™›XİØÛX\œ×Ùš[™Ù\œš[İ[Y\×Ø[™ÛİÛ™\ŠÜ\˜][Û˜[\Ü]
N‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
Bˆ›İÏXÜ™X]JÛÛ›‹Kİ\HŒŒ‹LLL‹[™HŒŒ‹LLLŠNÛX]™K˜\›İ™WÛX]™JÛÛ›‹›İÖÈšY—JBˆÛÛ›‹™^Xİ]J’S”ÑT•S•È\›Z[˜[ÜÛİÊÛİØÛÙK[\ŞYYWÚYY™™Xİ]™WÙœ›ÛKİ]\ÊHSQTÊ	ÌIËË	ÌŒ‹LKLIË	ÛX\Y	ÊH‹
K
JNØÛÛ›‹˜ÛÛ[Z]

NØÛÛ›‹˜ÛÜÙJ
BˆÛİ\˜ÙOXZ[Ù^Ü
\Ü]Èœ›Û˜XÚËÈ‹YX\LŒ‹[ÛNÛİÏVÔÛİÜXÊŒH‹‘šXİ[Û˜[‹ÌL–ÈŒÎŒ‹ŒMŒ—_JWJBˆ^×Ü\[[™Kœ™]šY]×Ú[\Ü
Ûİ\˜ÙK—Ü]\]\ØY×Ù\]\Ü]È\ŠBˆ×Ü\[[™K˜\WÚ[\Ü
š[\ÜÜ[—ÚY˜ÛÛ™š\›X][Û—İÚÙ[‹—Ü]\]˜XÚİ\×Ù\]\Ü]È˜˜XÚÈŠBˆ×Ü\[[™Kœ›Û˜XÚ×Ú[\Ü
š[\ÜÜ[—ÚY›X\[™ÈÛÜœ™Xİ[Ûˆ‹—Ü]\]
BˆÛÛ›Y‹˜ÛÛ›™Xİ
]
NØ][™[˜ÙOXÛÛ›‹™^Xİ]Jˆˆ”ÑSPÕİ]\ËXİX[Ú[—Ø]XİX[Ûİ]Ø]ˆÛİ\˜ÙK™]šY]×Ù›YË\İÚ[\ÜÜ[—ÚY”“ÓH][™[˜ÙWÙ^\ÈˆˆŠK™™]ÚÛ™J
Bˆ\ÜÙ\\J][™[˜ÙJOOJ›X]™H‹›Û™K›Û™K›X[X[‹›Û™K›Û™JBˆ\ÜÙ\ÛÛ›‹™^Xİ]J”ÑSPÕÓÕS•

ŠH”“ÓH[˜ÚÙ]™[ÈÒT‘H›ÛYØ˜XÚ×Ø]TÈ•SŠK™™]ÚÛ™J
VÌOOLˆX]™K˜Ø[˜Ù[ÛX]™JÛÛ›‹›İÖÈšY—K›X]™HØ[˜Ù[YŠBˆ][™[˜ÙOXÛÛ›‹™^Xİ]J”ÑSPÕXİX[Ú[—Ø]XİX[Ûİ]Ø]İ]\È”“ÓH][™[˜ÙWÙ^\ÈŠK™™]ÚÛ™J
Bˆ\ÜÙ\\J][™[˜ÙJOOJ›Û™K›Û™K[šÛ›İÛˆŠB‚‚™Yˆ\İÜ™\XÙ[Y[Üİ]\×ÛY™XŞXÛWÜ]ÚØ[™Û[š×İ˜[Y][ÛŠÜ\˜][Û˜[
N‚ˆ]K‹Ï[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
Bˆ\ÜÚYÛ›Y[\™\˜Ü™X]WØ\ÜÚYÛ›Y[
ÛÛ›‹XœÙ[Ù[\ŞYYWÚYXK™\XÙ[Y[Ù[\ŞYYWÚYX‹ˆİ\Ù]OHŒŒ‹LLL‹[™Ù]OHŒŒ‹LLL‹›Û™OH”Ú]HHŠBˆ™\œÙ]Üİ]\ÊÛÛ›‹\ÜÚYÛ›Y[ÈšY—K˜ÛÛ™š\›YYŠNÜ™\œÙ]Üİ]\ÊÛÛ›‹\ÜÚYÛ›Y[ÈšY—K˜ÛÛ\]YŠBˆÚ]]\İœ˜Z\Ù\Ê™\”™\XÙ[Y[\œ›ÜŠNœ™\œÙ]Üİ]\ÊÛÛ›‹\ÜÚYÛ›Y[ÈšY—Kœ[›™YŠBˆÚ]]\İœ˜Z\Ù\Ê™\”™\XÙ[Y[\œ›ÜŠNœ™\\]WØ\ÜÚYÛ›Y[
ÛÛ›‹\ÜÚYÛ›Y[ÈšY—KÈ›Û™Hˆ”Ú]HˆŸJBˆØ[˜Ù[Y\™\˜Ü™X]WØ\ÜÚYÛ›Y[
ÛÛ›‹XœÙ[Ù[\ŞYYWÚYXK™\XÙ[Y[Ù[\ŞYYWÚYX‹ˆİ\Ù]OHŒŒ‹LLLH‹[™Ù]OHŒŒ‹LLLH‹›Û™OH”Ú]HHŠBˆ™\œÙ]Üİ]\ÊÛÛ›‹Ø[˜Ù[YÈšY—K˜Ø[˜Ù[YŠBˆÚ]]\İœ˜Z\Ù\Ê™\”™\XÙ[Y[\œ›ÜŠNœ™\œÙ]Üİ]\ÊÛÛ›‹Ø[˜Ù[YÈšY—K˜ÛÛ™š\›YYŠBˆÚ]\İÛY[
Ü™X]WØ\

JH\ÈÛY[‚ˆ\ÜÙ\ÛY[œÜİ
ˆ‹Ø\KİŒKÜ™\XÙ[Y[[Ü\˜][ÛœËŞØ\ÜÚYÛ›Y[ÉÚY	×_KÜİ]\È‹ˆœÛÛ^Èœİ]\Èˆœ[›™YŸJKœİ]\×ØÛÙOOMBˆ\ÜÙ\ÛY[œ]Ú
ˆ‹Ø\KİŒKÜ™\XÙ[Y[[Ü\˜][ÛœËŞØ\ÜÚYÛ›Y[ÉÚY	×_H‹ˆœÛÛ^Èœİ]\Èˆœ[›™YŸJKœİ]\×ØÛÙOOMB‚‚™Yˆ\İÛ[ÛÛİ™\›\Ùš[\œ×Ø[™Û][Y^WÜ™\XÙ[Y[Üİ]ÊÜ\˜][Û˜[
N‚ˆ]K‹Ï[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
BˆÜ™X]JÛÛ›‹Kİ\HŒŒ‹LLÌH‹[™HŒŒ‹LKLˆŠBˆ™\Ü›İÏ\™\˜Ü™X]WØ\ÜÚYÛ›Y[
ÛÛ›‹XœÙ[Ù[\ŞYYWÚYXK™\XÙ[Y[Ù[\ŞYYWÚYX‹ˆİ\Ù]OHŒŒ‹LLL‹[™Ù]OHŒŒ‹LLLˆ‹›Û™OH”Ú]HHŠBˆ™\œÙ]Üİ]\ÊÛÛ›‹™\Ü›İÖÈšY—K˜ÛÛ™š\›YYŠBˆÛÛ›‹˜ÛÛ[Z]

BˆÚ]\İÛY[
Ü™X]WØ\

JH\ÈÛY[‚ˆ\ÜÙ\[ŠÛY[™Ù]
‹Ø\KİŒKÛX]™K[Ü\˜][ÛœÏÛ[ÛLŒ‹LŠKšœÛÛŠ
VÈ›X]™\È—JOOLBˆ\ÜÙ\[ŠÛY[™Ù]
‹Ø\KİŒKÛX]™K[Ü\˜][ÛœÏÛ[ÛLŒ‹LHŠKšœÛÛŠ
VÈ›X]™\È—JOOLBˆ\ÜÙ\ÛY[™Ù]
‹Ø\KİŒKÛX]™K[Ü\˜][ÛœÏÛ[ÛLŒ‹LHŠKšœÛÛŠ
VÈ˜˜[[˜ÙVYX\ˆ—OOLŒ‚ˆœ›ÛH\œÙ\šXÙ\È[\ÜÜÂˆİ]Ï[ÜË›[ÛÜİ]ÊÛÛ›‹Œ‹
Bˆ\ÜÙ\Üİ]ÖÜİŠ^JWVÈœ™\XÙH—H›Üˆ^H[ˆ
LLKLŠWOOVÌKKWBˆÙYZÏ[ÜËÙYZ×İšY]ÊÛÛ›‹ŒŒ‹LLL‹ŒŒ‹LLLŠBˆÛÜšÙ\]ÙYZÖÈ™[\ŞYY\È—VÌWBˆ\ÜÙ\ØÙ[È\H—H›ÜˆÙ[[ˆÛÜšÙ\–È˜Ù[È—VÎŒ×WOOVÈœ™\XÙ[Y[—JŒÂ‚‚]\İ›X\šËœ\˜[Y]š^™J™]K\×İÛÜšÚ[™Ë^XİY‹Âˆ
ŒŒ‹LL‹›Û™K˜[ÙJKˆ
ŒŒ‹LLL‹˜[ÙK˜[ÙJKˆ
ŒŒ‹LL‹YKYJK—JB™Yˆ\İÛX]™WÜ[˜ÚØÛÛ™›XİÜ™\ÜXİ×İÛÜš×ØØ[[™\ŠÜ\˜][Û˜[]K\×İÛÜšÚ[™Ë^XİY
N‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
BˆYˆ\×İÛÜšÚ[™È\È›İ›Û™N‚ˆÛÛ›‹™^Xİ]J’S”ÑT•S•ÈÚ]WØØ[[™\ŠØ[[™\—Ù]K^Wİ\K\×İÛÜšÚ[™ÊHSQTÊËËÊH‹
]KœÜXÚX[‹\×İÛÜšÚ[™ÊJBˆ›İÏXÜ™X]JÛÛ›‹Kİ\HŒŒ‹LLÈ‹[™HŒŒ‹LLLŠNÛX]™K˜\›İ™WÛX]™JÛÛ›‹›İÖÈšY—JBˆÚ[œÙ\Ü[˜Ú
ÛÛ›‹K]K˜Ø[[™\‹HŠÙ]JBˆ][O[X]™K›\İÛX]™JÛÛ›ŠVÌBˆ\ÜÙ\
›X]™WØ][™[˜ÙWØÛÛ™›Xİˆ[ˆ][VÈ™š[™[™ÜÈ—JH\È^XİYˆœ›ÛH\œÙ\šXÙ\È[\ÜÜÂˆšY]Ï[ÜËÙYZ×İšY]ÊÛÛ›‹ŒŒ‹LLÈ‹ŒŒ‹LLÈŠBˆÙ[]šY]ÖÈ™[\ŞYY\È—VÌVÈ˜Ù[È—VÊ[
]VËL—JKMÊWBˆ\ÜÙ\
Ù[™Ù]
š\ÜİYHŠH\ÈYJH\È^XİY‚‚™Yˆ\İØ\›İ™YØ[WÜWØYÙÜ™YØ]Wİ×Ù[Ù^JÜ\˜][Û˜[
N‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
Bˆ[OXÜ™X]JÛÛ›‹Kš[—Ù^H‹ŒŒ‹LLL‹ŒŒ‹LLL‹˜[HŠBˆOXÜ™X]JÛÛ›‹Kš[—Ù^H‹ŒŒ‹LLL‹ŒŒ‹LLL‹œHŠBˆX]™K˜\›İ™WÛX]™JÛÛ›‹[VÈšY—JNÛX]™K˜\›İ™WÛX]™JÛÛ›‹VÈšY—JBˆ\ÜÙ\X]™K˜˜[[˜ÙJÛÛ›‹KŒŠVÈ\ÙY—OOLKŒˆ\ÜÙ\X]™K˜\›İ™YÛX]™WØÛİ™\˜YÙJÛÛ›‹KŒŒ‹LLLŠVÈ˜Ûİ™\˜YÙH—OOH™[‚ˆ\ÜÙ\\JÛÛ›‹™^Xİ]J”ÑSPÕİ]\Ë™]šY]×Ù›YÈ”“ÓH][™[˜ÙWÙ^\ÈŠK™™]ÚÛ™J
JOOJ›X]™H‹›Û™JBˆÚ[œÙ\Ü[˜Ú
ÛÛ›‹KŒŒ‹LLL‹˜›İZ[™\ÈŠBˆX]™K—ÜŞ[˜×Ø][™[˜ÙJÛÛ›‹KÈŒŒ‹LLLŸJBˆ\ÜÙ\\JÛÛ›‹™^Xİ]J”ÑSPÕİ]\Ë™]šY]×Ù›YÈ”“ÓH][™[˜ÙWÙ^\ÈŠK™™]ÚÛ™J
JOOJ›X]™H‹›X]™WØ][™[˜ÙWØÛÛ™›XİŠB‚‚™Yˆ\İÜÚXÚ×ÛZ\ÛX]ÚØ[™Ü[˜ÚÜ™\Ù\™WØ›İÙš[™[™ÜÊÜ\˜][Û˜[
N‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
Bˆ›İÏXÜ™X]JÛÛ›‹KœÚXÚ×ÛX]™H‹ŒŒ‹LL‹ŒŒ‹LKLLH‹]šY[˜ÙWÜ™XÙZ]™YUYKˆ]šY[˜ÙWÜİ\Ù]OHŒŒ‹LL‹]šY[˜ÙWÙ[™Ù]OHŒŒ‹LLÌHŠBˆX]™K˜\›İ™WÛX]™JÛÛ›‹›İÖÈšY—JBˆ\ÜÙ\X]™K›\İÛX]™JÛÛ›ŠVÌVÈ™š[™[™ÜÈ—OOVÈœÚXÚ×ÛX]™WÙ]šY[˜ÙWÛZ\ÛX]Ú—BˆÚ[œÙ\Ü[˜Ú
ÛÛ›‹KŒŒ‹LL‹œÚXÚËX›İŠBˆš[™[™ÜÏ[X]™K›\İÛX]™JÛÛ›ŠVÌVÈ™š[™[™ÜÈ—Bˆ\ÜÙ\š[™[™ÜÏOVÈœÚXÚ×ÛX]™WÙ]šY[˜ÙWÛZ\ÛX]Ú‹›X]™WØ][™[˜ÙWØÛÛ™›Xİ—B‚‚™Yˆ\İÜ™\XÙ[Y[ÙY]Ü™]˜[Y]\×Û[š×Ø[™Ø[İÜ×Û[ØXœÙ[
Ü\˜][Û˜[
N‚ˆ]K‹Ï[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
Bˆİ\XÛÛ›‹™^Xİ]J’S”ÑT•S•È[\ŞYY\Ê[\ŞYYWØÛÙK˜[YK\™WÙ]Kİ]\ÊHSQTÊ	ÔQ	Ë	ÑšXİ[Û˜[	Ë	ÌŒŒLKLIË	ØXİ]™IÊHŠK›\İ›İÚYˆ[šÙYXÜ™X]JÛÛ›‹Kİ\HŒŒ‹LLL‹[™HŒŒ‹LLLˆŠBˆ\ÜÚYÛ›Y[\™\˜Ü™X]WØ\ÜÚYÛ›Y[
ÛÛ›‹XœÙ[Ù[\ŞYYWÚYXK™\XÙ[Y[Ù[\ŞYYWÚYX‹ˆİ\Ù]OHŒŒ‹LLL‹[™Ù]OHŒŒ‹LLLˆ‹›Û™OHH‹X]™WÜ™\]Y\İÚY[[šÙYÈšY—JBˆÚ]]\İœ˜Z\Ù\Ê™\”™\XÙ[Y[\œ›Ü‹X]ÚH˜™[Û™ÈŠN‚ˆ™\\]WØ\ÜÚYÛ›Y[
ÛÛ›‹\ÜÚYÛ›Y[ÈšY—KÈ˜XœÙ[[\ŞYYRY›İ\ŸJBˆÚ]]\İœ˜Z\Ù\Ê™\”™\XÙ[Y[\œ›Ü‹X]ÚH˜Ûİ™\™YŠN‚ˆ™\\]WØ\ÜÚYÛ›Y[
ÛÛ›‹\ÜÚYÛ›Y[ÈšY—KÈœİ\]HˆŒŒ‹LLMH‹™[™]HˆŒŒ‹LLMHŸJBˆÛÜÙO\™\˜Ü™X]WØ\ÜÚYÛ›Y[
ÛÛ›‹XœÙ[Ù[\ŞYYWÚYS›Û™K™\XÙ[Y[Ù[\ŞYYWÚYX‹ˆİ\Ù]OHŒŒ‹LLLÈ‹[™Ù]OHŒŒ‹LLLÈ‹›Û™OHHŠBˆÚ[™ÙY\™\\]WØ\ÜÚYÛ›Y[
ÛÛ›‹ÛÜÙVÈšY—KÈ›Û™Hˆˆ‹››İHˆ™šXİ[Û˜[ŸJBˆ\ÜÙ\Ú[™ÙYÈ˜XœÙ[[\ŞYYRY—H\È›Û™H[™Ú[™ÙYÈ›Û™H—OOHˆ‚ˆ\ÜÙ\ÛÛ›‹™^Xİ]J”ÑSPÕÓÕS•

ŠH”“ÓH]Y]ÛÙÈÒT‘HXİ[ÛIÜ™\XÙ[Y[\]IÈŠK™™]ÚÛ™J
VÌOOLB‚‚]\İ›X\šËœ\˜[Y]š^™Jœ^[ØY‹ÂˆÈ›X]™U\Hˆ˜[›X[ÛX]™H‹œİ\]HˆŒŒ‹LLLH‹™[™]HˆŒŒ‹LLL‹œÜ[Ûˆˆ™[ŸKˆÈ›X]™U\Hˆš[—Ù^H‹œİ\]HˆŒŒ‹LLL‹™[™]HˆŒŒ‹LLLH‹œÜ[Ûˆˆ˜[HŸK—JB™Yˆ\İØ˜YÛX]™WØØ[[™\—Ú[œ]×Ø\™WØÛÛ›ÛYÚÙ\œ›ÜœÊÜ\˜][Û˜[^[ØY
N‚ˆ]KËÏ[Ü\˜][Û˜[ˆ^[ØY^È™[\ŞYYRY˜K
Šœ^[ØYBˆÚ]\İÛY[
Ü™X]WØ\

JH\ÈÛY[‚ˆ™\ÜÛœÙOXÛY[œÜİ
‹Ø\KİŒKÛX]™K[Ü\˜][ÛœÈ‹œÛÛ\^[ØY
Bˆ\ÜÙ\™\ÜÛœÙKœİ]\×ØÛÙH[ˆÍKŒŸBˆ\ÜÙ\‹˜ÛÛ›™Xİ
]
K™^Xİ]J”ÑSPÕÓÕS•

ŠH”“ÓHX]™WÜ™\]Y\İÈŠK™™]ÚÛ™J
VÌOOL‚‚™Yˆ\İÛÜ\˜][Û˜[İZWÚ[š]X[Û[ÛÚ\×Ù[˜[ZXÊ
N‚ˆØÜš\T]
œ\ÙM]ZKšœÈŠKœ™XYİ^
[˜ÛÙ[™ÏH]‹NŠBˆ\ÜÙ\œÙ[XİY[ÛIÌŒ‹L	Èˆ›İ[ˆØÜš\ˆ\ÜÙ\››İË™Ù][YX\Š
Hˆ[ˆØÜš\[™››İË™Ù][Û

JÌHˆ[ˆØÜš\‚‚™Yˆ\İŞ×Ù\š]˜][Û—İ\Ù\×Ø]]Üš]]]™WİÛÜš×ØØ[[™\ŠÜ\˜][Û˜[\Ü]
N‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
BˆÛÛ›‹™^Xİ]J’S”ÑT•S•ÈÚ]WØØ[[™\ŠØ[[™\—Ù]K^Wİ\K\×İÛÜšÚ[™ÊHSQTÊ	ÌŒ‹LL	Ë	ÜÜXÚX[	ËJHŠBˆÛÛ›‹™^Xİ]J’S”ÑT•S•ÈÚ]WØØ[[™\ŠØ[[™\—Ù]K^Wİ\K\×İÛÜšÚ[™ÊHSQTÊ	ÌŒ‹LLL	Ë	ÚÛY^IË
HŠBˆ›İÏXÜ™X]JÛÛ›‹Kİ\HŒŒ‹LLÈ‹[™HŒŒ‹LLLŠNÛX]™K˜\›İ™WÛX]™JÛÛ›‹›İÖÈšY—JBˆÛÛ›‹™^Xİ]J’S”ÑT•S•È\›Z[˜[ÜÛİÊÛİØÛÙK[\ŞYYWÚYY™™Xİ]™WÙœ›ÛKİ]\ÊHSQTÊ	ÌIËË	ÌŒ‹LKLIË	ÛX\Y	ÊH‹
K
JNØÛÛ›‹˜ÛÛ[Z]

NØÛÛ›‹˜ÛÜÙJ
BˆÛİ\˜ÙOXZ[Ù^Ü
\Ü]È˜Ø[[™\‹È‹YX\LŒ‹[ÛNÛİÏVÔÛİÜXÊŒH‹‘šXİ[Û˜[‹Âˆ–ÈŒÎŒ‹ŒMŒ—KL–ÈŒÎŒ‹ŒMŒ—_JWJBˆ™]šY]Ï^×Ü\[[™Kœ™]šY]×Ú[\Ü
Ûİ\˜ÙK—Ü]\]\ØY×Ù\]\Ü]È\ŠBˆ×Ü\[[™K˜\WÚ[\Ü
™]šY]Ëš[\ÜÜ[—ÚY™]šY]Ë˜ÛÛ™š\›X][Û—İÚÙ[‹—Ü]\]˜XÚİ\×Ù\]\Ü]È˜˜XÚÈŠBˆÛÛ›Y‹˜ÛÛ›™Xİ
]
Bˆ›İÜÏ^Ü–ÈÛÜš×Ù]H—N™Xİ
ŠH›Üˆˆ[ˆÛÛ›‹™^Xİ]J”ÑSPÕÛÜš×Ù]Kİ]\Ë™]šY]×Ù›YÈ”“ÓH][™[˜ÙWÙ^\ÈÒT‘HÛÜš×Ù]HSˆ
	ÌŒ‹LL	Ë	ÌŒ‹LLL	ÊHŠ_Bˆ\ÜÙ\›İÜÖÈŒŒ‹LL—VÈœ™]šY]×Ù›YÈ—OOH›X]™WØ][™[˜ÙWØÛÛ™›Xİ‚ˆ\ÜÙ\›İÜÖÈŒŒ‹LLL—VÈœİ]\È—OOH››Ü›X[ˆ[™›İÜÖÈŒŒ‹LLL—VÈœ™]šY]×Ù›YÈ—H\È›Û™B‚‚]\İ›X\šËœ\˜[Y]š^™J™]KØ[[™\—Ù[K^XİØÛÛ™›Xİ‹Âˆ
ŒŒ‹LL‹›Û™K˜[ÙJKˆ
ŒŒ‹LLNH‹
šÛY^H‹º¬ ; àH;g-;'oŠK˜[ÙJKˆ
ŒŒ‹LLŒˆ‹
œÜXÚX[‹Kº¬ ; àH;a¨;&¥:­ï:ë-ŠKYJK—JB™Yˆ\İŞ×Ü™]šY]×ÛX]™WØÛÛ™›Xİİ\Ù\×İÛÜš×ØØ[[™\ŠˆÜ\˜][Û˜[\Ü]]KØ[[™\—Ù[K^XİØÛÛ™›XİŠN‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
BˆX\[™×Ù]OHŒŒ‹LKLH‚ˆÛÛ›‹™^Xİ]J’S”ÑT•S•È\›Z[˜[ÜÛİÊÛİØÛÙK[\ŞYYWÚYY™™Xİ]™WÙœ›ÛKİ]\ÊHSQTÊ	ÌIËËË	ÛX\Y	ÊH‹
KX\[™×Ù]JJBˆYˆØ[[™\—Ù[N‚ˆÛÛ›‹™^Xİ]J’S”ÑT•S•ÈÚ]WØØ[[™\ŠØ[[™\—Ù]K^Wİ\K\×İÛÜšÚ[™ËX™[
HSQTÊËËËÊH‹
]K
˜Ø[[™\—Ù[JJBˆX]™WÜİ\X]™WÙ[™JŒŒ‹LLÈ‹ŒŒ‹LLLŠHYˆ]OOHŒŒ‹LLˆ[ÙH

ŒŒ‹LLN‹ŒŒ‹LLŒŠHYˆ]OOHŒŒ‹LLNHˆ[ÙH
]K]JJBˆ›İÏXÜ™X]JÛÛ›‹Kİ\[X]™WÜİ\[™[X]™WÙ[™
NÛX]™K˜\›İ™WÛX]™JÛÛ›‹›İÖÈšY—JNØÛÛ›‹˜ÛÛ[Z]

NØÛÛ›‹˜ÛÜÙJ
Bˆ^OZ[
]VËL—JNÜÛİ\˜ÙOXZ[Ù^Ü
\Ü]Èœ™]šY]ËXØ[[™\‹È‹YX\LŒ‹[ÛNˆÛİÏVÔÛİÜXÊŒH‹‘šXİ[Û˜[‹Ù^N–ÈŒÎMH‹ŒMŒH—_JWJBˆ™]šY]Ï^×Ü\[[™Kœ™]šY]×Ú[\Ü
Ûİ\˜ÙK—Ü]\]\ØY×Ù\]\Ü]È\ŠBˆÛÙ\ÏVÙš[™[™ÖÈ˜ÛÙH—H›Üˆš[™[™È[ˆ™]šY]Ë™š[™[™Ü×Bˆ\ÜÙ\
›X]™WØÛÛ™›Xİˆ[ˆÛÙ\ÊH\È^XİØÛÛ™›Xİˆ×Ü\[[™K˜\WÚ[\Ü
™]šY]Ëš[\ÜÜ[—ÚY™]šY]Ë˜ÛÛ™š\›X][Û—İÚÙ[‹—Ü]\]˜XÚİ\×Ù\]\Ü]È˜˜XÚÈŠBˆÛÛ›Y‹˜ÛÛ›™Xİ
]
NØ][™[˜ÙOXÛÛ›‹™^Xİ]J”ÑSPÕİ]\Ë™]šY]×Ù›YÈ”“ÓH][™[˜ÙWÙ^\ÈÒT‘H[\ŞYYWÚYOÈS‘ÛÜš×Ù]OOÈ‹
K]JJK™™]ÚÛ™J
Bˆ\ÜÙ\
][™[˜ÙVÈœ™]šY]×Ù›YÈ—OOH›X]™WØ][™[˜ÙWØÛÛ™›XİŠH\È^XİØÛÛ™›Xİ‚‚]\İ›X\šËœ\˜[Y]š^™JœÜ[ÛœË^XİØÛÛ™›Xİ‹Ê
	Ø[IË
K˜[ÙJK

	Ø[IË	ÜIÊKYJWJB™Yˆ\İŞ×Ü™]šY]×ØYÙÜ™YØ]\×Ú[—Ù^WØÛİ™\˜YÙJÜ\˜][Û˜[\Ü]Ü[ÛœË^XİØÛÛ™›Xİ
N‚ˆ]KËÏ[Ü\˜][Û˜[ØÛÛ›Y‹˜ÛÛ›™Xİ
]
BˆÛÛ›‹™^Xİ]J’S”ÑT•S•È\›Z[˜[ÜÛİÊÛİØÛÙK[\ŞYYWÚYY™™Xİ]™WÙœ›ÛKİ]\ÊHSQTÊ	ÌIËË	ÌŒ‹LKLIË	ÛX\Y	ÊH‹
K
JBˆ›ÜˆÜ[Ûˆ[ˆÜ[ÛœÎ‚ˆ›İÏXÜ™X]JÛÛ›‹Kš[—Ù^H‹ŒŒ‹LLM‹ŒŒ‹LLM‹Ü[ÛŠNÛX]™K˜\›İ™WÛX]™JÛÛ›‹›İÖÈšY—JBˆÛÛ›‹˜ÛÛ[Z]

NØÛÛ›‹˜ÛÜÙJ
BˆÛİ\˜ÙOXZ[Ù^Ü
\Ü]Èœ™]šY]ËZ[™\ËÈ‹YX\LŒ‹[ÛNˆÛİÏVÔÛİÜXÊŒH‹‘šXİ[Û˜[‹ÌM–ÈŒÎLˆ‹ŒMŒ—_JWJBˆ™]šY]Ï^×Ü\[[™Kœ™]šY]×Ú[\Ü
Ûİ\˜ÙK—Ü]\]\ØY×Ù\]\Ü]È\ŠBˆ\ÜÙ\
›X]™WØÛÛ™›Xİˆ[ˆÙ–È˜ÛÙH—H›Üˆˆ[ˆ™]šY]Ë™š[™[™Ü×JH\È^XİØÛÛ™›Xİˆ×Ü\[[™K˜\WÚ[\Ü
™]šY]Ëš[\ÜÜ[—ÚY™]šY]Ë˜ÛÛ™š\›X][Û—İÚÙ[‹—Ü]\]˜XÚİ\×Ù\]\Ü]È˜˜XÚÈŠBˆÛÛ›Y‹˜ÛÛ›™Xİ
]
NÙ›YÏXÛÛ›‹™^Xİ]J”ÑSPÕ™]šY]×Ù›YÈ”“ÓH][™[˜ÙWÙ^\ÈÒT‘H[\ŞYYWÚYOÈS‘ÛÜš×Ù]OIÌŒ‹LLM	È‹
K
JK™™]ÚÛ™J
VÌBˆ\ÜÙ\›YÈOH
›X]™WØ][™[˜ÙWØÛÛ™›XİˆYˆ^XİØÛÛ™›Xİ[ÙHœ\X[ÛX]™WÜ™]šY]ÈŠB