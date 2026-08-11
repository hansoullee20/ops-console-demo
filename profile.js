(function(){
  function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));}
  function employeeByName(name){
    try{return employees.find(e=>e.name===name)||null}catch(_){return null}
  }
  function stateClass(state){return state==='병가'?'red':state==='대체'?'purple':'green'}
  function cellClass(c){
    if(c.issue) return 'red';
    return c.type==='ok'?'green':c.type==='replacement'?'purple':c.type==='leave'?'blue':c.type==='sick'?'red':'gray';
  }
  window.showEmployeeProfile=function(name){
    const e=employeeByName(name); if(!e) return;
    const counts={ok:0,leave:0,sick:0,replacement:0,issue:0};
    e.cells.forEach(c=>{if(Object.prototype.hasOwnProperty.call(counts,c.type))counts[c.type]++;if(c.issue)counts.issue++});
    const week=e.cells.map((c,i)=>{
      const day=(typeof days!=='undefined'&&days[i])?days[i].dow.replace(' · 오늘',''):String(i+1);
      return `<div class="profileday"><b>${esc(day)}</b><span class="tag ${cellClass(c)}">${esc(c.label)}</span></div>`;
    }).join('');
    const dtitle=document.getElementById('dtitle'), dsub=document.getElementById('dsub'), dbody=document.getElementById('dbody'), dfoot=document.getElementById('dfoot'), wrap=document.getElementById('drawerWrap');
    if(!dtitle||!dsub||!dbody||!dfoot||!wrap) return;
    dtitle.textContent=e.name;
    dsub.textContent=`직원 프로필 · ${e.zone}`;
    dbody.innerHTML=`
      <div class="profilehero">
        <div class="profileavatar">${esc(e.name[0])}</div>
        <div><h3>${esc(e.name)}</h3><div class="profilemeta">${esc(e.zone)}</div><div class="profilestate"><span class="tag ${stateClass(e.state)}">${esc(e.state)}</span></div></div>
      </div>
      <div class="box"><div class="kv">
        <div class="k">담당구역</div><div>${esc(e.zone)}</div>
        <div class="k">입사일</div><div>${esc(e.hire)}</div>
        <div class="k">계약만료</div><div>${esc(e.end)}</div>
        <div class="k">연차 잔여</div><div>${esc(e.leave)}일</div>
        <div class="k">지문슬롯</div><div>${esc(e.slot)}</div>
        <div class="k">현재상태</div><div><span class="tag ${stateClass(e.state)}">${esc(e.state)}</span></div>
      </div></div>
      <div class="profileweektitle">이번 주</div>
      <div class="profileweek">${week}</div>
      <div class="profilesummary">정상 ${counts.ok} · 연차 ${counts.leave} · 병가 ${counts.sick} · 대체 ${counts.replacement} · 확인 ${counts.issue}</div>`;
    dfoot.innerHTML='<button class="btn" data-profile-nav="attendance">근태 보기</button><button class="btn" data-profile-nav="leave">휴가 보기</button><button class="btn primary" data-profile-close>닫기</button>';
    wrap.classList.add('open');
  };
  function nameFromTarget(t){
    const selectors=['.pname','.namecell b','#attendanceGrid td:first-child b','#employeeTable td:first-child b','#page-leave tbody td:first-child b'];
    for(const sel of selectors){const el=t.closest(sel);if(el){const n=el.textContent.trim();if(employeeByName(n)) return n;}}
    return null;
  }
  document.addEventListener('click',function(ev){
    const nav=ev.target.closest('[data-profile-nav]');
    if(nav){ev.preventDefault();ev.stopPropagation();const page=nav.getAttribute('data-profile-nav');const b=document.querySelector(`#topNav button[data-page="${page}"]`);if(b)b.click();if(window.closeDrawer)closeDrawer();return;}
    if(ev.target.closest('[data-profile-close]')){ev.preventDefault();ev.stopPropagation();if(window.closeDrawer)closeDrawer();return;}
    const name=nameFromTarget(ev.target); if(!name) return;
    ev.preventDefault();ev.stopPropagation();ev.stopImmediatePropagation();showEmployeeProfile(name);
  },true);
})();
