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
        if source.name.startswith(("0007_", "0008_", "0009_")): continue
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
    through8=tmp_path/"migrations-v8";through8.mkdir()
    for source in sorted(migrations.glob("*.sql")):
        if source.name.startswith("0009_"): continue
        shutil.copy2(source,through8/source.name)
    result=migrate.run_migrations(database,migrations_dir=through8,backups_dir=backups)
    assert result.applied==[7,8] and result.backup_path and result.backup_path.exists()
    conn=db.connect(database)
    upgraded=conn.execute(
        "SELECT work_date,start_date,end_date,key_received FROM replacement_assignments WHERE id=?",
        (assignment,),
    ).fetchone()
    assert tuple(upgraded)==("2026-08-10","2026-08-10","2026-08-10",0)
    assert migrate.run_migrations(database,migrations_dir=through8,backups_dir=backups).applied==[]


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
    conn.execute("INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('001',?,'2026-01-01…8215 tokens truncated…003e</div><div class="drawerfoot" id="dfoot"></div></aside></div><div id="toast"></div>
<button class="ai-fab" onclick="openAI()">✦ AI 업무도우미 <span class="free">MOCK</span></button><div class="ai-panel-wrap" id="aiWrap"><div class="ai-scrim" onclick="closeAI()"></div><aside class="ai-panel"><div class="ai-head"><div class="ai-head-top"><h2>AI 업무도우미</h2><div class="local-state" id="localState">데모 응답</div><button class="ai-close" onclick="closeAI()">×</button></div><div class="ai-provider"><button class="provider-btn on" data-provider="claude" onclick="setProvider('claude')">Claude</button><button class="provider-btn" data-provider="codex" onclick="setProvider('codex')">GPT · Codex</button></div></div><div class="ai-context"><span class="ctx">운영</span><span class="ctx">직원 18명</span></div><div class="ai-chat" id="aiChat"><div class="msg ai"><div class="bubble">현재 목데이터를 기준으로 답합니다. 예: “오늘 결원 있어?”</div></div></div><div class="ai-compose"><div class="quick"><button onclick="askQuick('오늘 결원과 대체 현황 알려줘')">오늘 결원</button><button onclick="askQuick('확인 필요한 항목만 정리해줘')">확인 필요</button><button onclick="askQuick('김가람 병가에서 뭐가 문제야?')">병가 확인</button><button onclick="askQuick('오늘 업무 보고 문장 써줘')">업무보고</button></div><div class="composebox"><textarea id="aiInput" placeholder="예: 오늘 결원 있어?"></textarea><button class="send" onclick="sendAI()">↑</button></div><div class="ai-note">공개 데모 · 실제 Claude/GPT 연결 아님</div></div></aside></div>
<script>
// Operations data is loaded by data-source.js: from the API in operational
// mode, or from the generated snapshot in the public demo. It is never both.
let days=[];
let employees=[];
let opsMode='weekly',issuesOnly=false,selectedDay=1;function renderOps(){document.querySelectorAll('#opsView button').forEach(b=>b.classList.toggle('on',b.dataset.view===opsMode));document.getElementById('periodTitle').textContent=periodTitleFor(opsMode);let c=employees.map(e=>e.cells[selectedDay]);document.getElementById('opsBrief').innerHTML=`재직 <b>18</b> · 정상 <b>${c.filter(x=>x.type==='ok').length}</b> · 휴가/병가 <b>${c.filter(x=>['leave','sick'].includes(x.type)).length}</b> · 대체 <b>${c.filter(x=>x.type==='replacement').length}</b>`;document.getElementById('issueCount').textContent=employees.reduce((n,e)=>n+e.cells.filter(x=>x.issue).length,0);document.getElementById('issueBtn').classList.toggle('on',issuesOnly);opsMode==='weekly'?renderWeekly():opsMode==='daily'?renderDaily():renderMonthly()}
function renderWeekly(){let list=employees.filter(e=>!issuesOnly||e.cells.some(c=>c.issue)),h='<section class="panel board"><div class="weekgrid"><div class="wrow whead"><div>직원 · 담당구역</div>';days.forEach(d=>h+=`<div class="dayhead ${d.today?'today':''}"><div>${d.dow}</div><div class="num">${d.num}</div></div>`);h+='</div>';list.forEach(e=>{h+=`<div class="wrow"><div class="person"><div class="avatar">${e.name[0]}</div><div><div class="pname">${e.name}</div><div class="zone">${e.zone}</div></div></div>`;e.cells.forEach((c,i)=>h+=`<div class="cell ${days[i].today?'today':''}" onclick='openCell(${JSON.stringify(e.name)},${JSON.stringify(e.zone)},${i},${JSON.stringify(c)})'>${c.issue?'<span class="marker"></span>':''}<div class="shift">${c.shift}</div><span class="pill ${c.type}">${c.label}</span><div class="punch">${c.punch||''}</div></div>`);h+='</div>'});document.getElementById('opsContent').innerHTML=h+'</div></section>'}
function renderDaily(){let rows=employees.filter(e=>!issuesOnly||e.cells[selectedDay].issue).sort((a,b)=>(b.cells[selectedDay].issue?1:0)-(a.cells[selectedDay].issue?1:0)),h='<section class="panel daily"><div><div class="panelhead"><h1>8월 11일 화요일</h1></div><table><thead><tr><th>직원</th><th>구역</th><th>예정</th><th>실제</th><th>상태</th></tr></thead><tbody>';rows.forEach(e=>{let c=e.cells[selectedDay];h+=`<tr class="${c.issue?'issueRow':''}" onclick='openCell(${JSON.stringify(e.name)},${JSON.stringify(e.zone)},${selectedDay},${JSON.stringify(c)})'><td><b>${e.name}</b></td><td>${e.zone}</td><td>${c.shift}</td><td>${c.punch||'—'}</td><td><span class="tag ${c.issue?'red':c.type==='ok'?'green':c.type==='replacement'?'purple':'amber'}">${c.label}</span></td></tr>`});h+='</tbody></table></div>'+dailyAside()+'</section>';document.getElementById('opsContent').innerHTML=h}
let monthStats={};
function renderMonthly(){let h='<section class="panel"><div class="monthwrap"><div class="monthgrid">';['일','월','화','수','목','금','토'].forEach(d=>h+=`<div class="mcell mhead">${d}</div>`);for(let i=0;i<6;i++)h+='<div class="mcell"></div>';for(let d=1;d<=31;d++){let s=monthStats[d]||{};h+=`<div class="mcell ${d===11?'today':''}"><div class="mnum">${d}</div>${s.issue?`<span class="mchip red">확인 ${s.issue}</span>`:''}${s.leave?`<span class="mchip blue">휴가 ${s.leave}</span>`:''}${s.sick?`<span class="mchip red">병가 ${s.sick}</span>`:''}${s.replace?`<span class="mchip purple">대체 ${s.replace}</span>`:''}</div>`}document.getElementById('opsContent').innerHTML=h+'</div></div></section>'}
document.querySelectorAll('#opsView button').forEach(b=>b.onclick=()=>{opsMode=b.dataset.view;renderOps()});function toggleIssues(){issuesOnly=!issuesOnly;renderOps()}
function renderAttendance(){renderAttendanceGrid()}
function renderEmployees(){document.getElementById('employeeTable').innerHTML=employees.map(e=>`<tr onclick="openGeneric('${e.name}','${e.zone}','입사 ${e.hire} · 계약 ${e.end}','연차 ${e.leave}일 · 지문 ${e.slot}')"><td><b>${e.name}</b></td><td>${e.zone}</td><td>${e.hire}</td><td>${e.end}</td><td>${e.leave}일</td><td><span class="tag ${e.state==='병가'?'red':e.state==='대체'?'purple':'green'}">${e.state}</span></td><td>${e.slot}</td></tr>`).join('')}
document.querySelectorAll('#topNav button').forEach(b=>b.onclick=()=>{document.querySelectorAll('#topNav button').forEach(x=>x.classList.remove('on'));b.classList.add('on');document.querySelectorAll('.page').forEach(p=>p.classList.remove('on'));document.getElementById('page-'+b.dataset.page).classList.add('on')});
function openCell(name,zone,i,c){dtitle.textContent=name;dsub.textContent=`${days[i].date} · ${zone}`;dbody.innerHTML=`<div class="box"><div class="kv"><div class="k">예정</div><div>${c.shift}</div><div class="k">상태</div><div><b>${c.label}</b></div><div class="k">기록</div><div>${c.punch||'—'}</div></div></div>${c.issue?`<div class="alert"><b>확인 필요</b><br>${c.detail}</div>`:''}`;dfoot.innerHTML='<button class="btn" onclick="closeDrawer()">닫기</button><button class="btn primary" onclick="toast(\'목업: 조치\')">조치하기</button>';drawerWrap.classList.add('open')}function openGeneric(title,sub,main,note){dtitle.textContent=title;dsub.textContent=sub;dbody.innerHTML=`<div class="box"><div class="kv"><div class="k">정보</div><div>${main}</div><div class="k">메모</div><div>${note}</div></div></div>`;drawerWrap.classList.add('open')}function closeDrawer(){drawerWrap.classList.remove('open')}function toast(t){let e=document.getElementById('toast');e.textContent=t;e.style.display='block';setTimeout(()=>e.style.display='none',1200)}
function openAI(){aiWrap.classList.add('open')}function closeAI(){aiWrap.classList.remove('open')}function setProvider(p){document.querySelectorAll('.provider-btn').forEach(b=>b.classList.toggle('on',b.dataset.provider===p));localState.textContent=p==='claude'?'Claude 데모':'GPT/Codex 데모'}function askQuick(q){aiInput.value=q;sendAI()}function sendAI(){let q=aiInput.value.trim();if(!q)return;aiChat.innerHTML+=`<div class="msg user"><div class="bubble">${q}</div></div>`;aiInput.value='';let a='현재 목데이터 기준으로 확인했습니다.',tool='get_current_view()';if(q.includes('결원')||q.includes('대체')){a='오늘 미배치 결원은 <b>1건</b>입니다. 박나래 담당 공학관 3층에 대체인력이 아직 배정되지 않았습니다.';tool='get_replacement_status()'}else if(q.includes('확인')){a='<b>4건</b>입니다. 김가람 병가 증빙기간, 박나래 결원, 이도연 휴가·근태 충돌, 최라온 다중 태그입니다.';tool='get_issues()'}else if(q.includes('김가람')||q.includes('병가')){a='김가람의 병가 신청은 8/4–9/11인데 진단서는 8/4–8/31까지입니다. 추가 증빙 또는 신청기간 정정이 필요합니다.';tool='get_leave(김가람)'}else if(q.includes('보고')){a='<b>업무보고 초안</b><br>8월 11일 병가 증빙 불일치 1건, 결원·대체 미배치 1건, 휴가·근태 충돌 1건, 다중 지문기록 1건을 확인하여 조치 중입니다.';tool='get_daily_summary()'}setTimeout(()=>{aiChat.innerHTML+=`<div class="msg ai"><div class="bubble"><div class="tooltrace">${tool}</div>${a}</div></div>`;aiChat.scrollTop=aiChat.scrollHeight},180)}aiInput.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendAI()}});
</script><script src="./profile.js"></script>
<!--OPS_DEMO_INJECT-->
<script src="./data-source.js"></script>
<script src="./import-ui.js"></script>
<script src="./phase4-ui.js"></script>
<script src="./safety-ui.js"></script>
<script src="./month-close-ui.js"></script>
</body></html>
