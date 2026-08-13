"""Deterministic operational leave rules and audit trail."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.services import work_calendar

API_TO_DB = {
    "annual_leave": "annual",
    "half_day": "half_day",
    "sick_leave": "sick",
    "other_authorized_leave": "other",
}
DB_TO_API = {value: key for key, value in API_TO_DB.items()}
BLOCKING_STATUSES = ("requested", "approved")


class LeaveError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _employee(conn: sqlite3.Connection, employee_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if row is None:
        raise LeaveError("직원을 찾을 수 없습니다.")
    return row


def _validate_employment(employee: sqlite3.Row, start_date: str, end_date: str) -> None:
    if start_date < employee["hire_date"]:
        raise LeaveError("입사일 이전에는 휴가를 등록할 수 없습니다.")
    if employee["end_date"] and end_date > employee["end_date"]:
        raise LeaveError("퇴사일 이후에는 휴가를 등록할 수 없습니다.")


def _portion_set(leave_type: str, half_day_period: str | None) -> set[str]:
    if leave_type == "half_day":
        return {half_day_period or ""}
    return {"am", "pm"}


def _assert_no_overlap(
    conn: sqlite3.Connection, employee_id: int, start_date: str, end_date: str,
    leave_type: str, half_day_period: str | None, exclude_id: int | None = None,
) -> None:
    rows = conn.execute(
        """SELECT id, leave_type, half_day_period, start_date, end_date
             FROM leave_requests
            WHERE employee_id = ? AND status IN ('requested','approved')
              AND start_date <= ? AND end_date >= ?
              AND (? IS NULL OR id != ?)""",
        (employee_id, end_date, start_date, exclude_id, exclude_id),
    ).fetchall()
    new_portions = _portion_set(leave_type, half_day_period)
    for row in rows:
        overlap_start = max(start_date, row["start_date"])
        overlap_end = min(end_date, row["end_date"])
        for iso in work_calendar.dates_between(overlap_start, overlap_end):
            if not work_calendar.is_working_day(conn, iso):
    …64498 tokens truncated…003e</div><div class="drawerfoot" id="dfoot"></div></aside></div><div id="toast"></div>
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
