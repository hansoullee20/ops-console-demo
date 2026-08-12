(function(){
  'use strict';
  var people=[
    {id:'01',name:'직원 01',zone:'본관 1층',shift:'07:00–16:00',state:'정상',punch:'07:02 · 16:08'},
    {id:'03',name:'직원 03',zone:'도서관 2층',shift:'07:00–16:00',state:'확인',punch:'07:04 · 퇴근 없음'},
    {id:'07',name:'직원 07',zone:'공학관 3층',shift:'07:00–16:00',state:'휴가',punch:'지문 없음'},
    {id:'12',name:'직원 12',zone:'학생회관',shift:'08:00–17:00',state:'정상',punch:'07:55 · 17:03'},
    {id:'16',name:'직원 16',zone:'연구동 1층',shift:'08:00–17:00',state:'정상',punch:'07:58 · 17:01'}
  ];
  var titles={today:'오늘',issues:'확인할 항목',people:'직원',more:'더보기'};
  var screens=[].slice.call(document.querySelectorAll('.mobile-screen'));
  var navs=[].slice.call(document.querySelectorAll('[data-nav]'));
  var backdrop=document.getElementById('sheetBackdrop');
  var content=document.getElementById('sheetContent');
  var toast=document.getElementById('mobileToast');

  function setPeriod(period){
    document.querySelectorAll('[data-period]').forEach(function(button){button.classList.toggle('active',button.dataset.period===period)});
    document.querySelectorAll('[data-period-view]').forEach(function(view){view.classList.toggle('active',view.dataset.periodView===period)});
  }

  function esc(v){return String(v).replace(/[&<>"']/g,function(c){return({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'})[c]})}
  function go(name){
    screens.forEach(function(s){s.classList.toggle('active',s.dataset.screen===name)});
    navs.forEach(function(n){n.classList.toggle('active',n.dataset.nav===name)});
    document.getElementById('screenTitle').textContent=titles[name];
    window.scrollTo(0,0);
  }
  function showToast(message){toast.textContent=message;toast.hidden=false;clearTimeout(showToast.timer);showToast.timer=setTimeout(function(){toast.hidden=true},1800)}
  function openSheet(html){content.innerHTML=html;backdrop.hidden=false;document.body.style.overflow='hidden'}
  function closeSheet(){backdrop.hidden=true;document.body.style.overflow=''}
  function personSheet(name){
    var p=people.find(function(x){return x.name===name})||people[0];
    openSheet('<div class="profile-top"><span class="avatar">'+esc(p.id)+'</span><div><h2 id="sheetTitle">'+esc(p.name)+'</h2><p>'+esc(p.zone)+'</p></div></div>'+ 
      '<div class="detail-grid"><span>오늘 상태</span><span>'+esc(p.state)+'</span><span>근무시간</span><span>'+esc(p.shift)+'</span><span>지문기록</span><span>'+esc(p.punch)+'</span><span>지문슬롯</span><span>'+esc(p.id)+'</span></div>'+ 
      '<div class="sheet-actions"><button data-sheet-action="note">메모 남기기</button><button class="primary-action" data-sheet-action="attendance">근태 보기</button></div>');
  }
  function actionSheet(kind){
    if(kind==='replacement') openSheet('<h2 id="sheetTitle">대체 인력 배정</h2><p class="prototype-note">공학관 3층 · 오늘 07:00–16:00</p><div class="detail-grid"><span>결원</span><span>직원 07</span><span>대체 후보</span><span>직원 19 (가능)</span><span>겹치는 배치</span><span>없음</span></div><div class="sheet-actions"><button id="cancelSheet">취소</button><button class="primary-action" data-sheet-action="save-replacement">배정하기</button></div>');
    else if(kind==='leave') openSheet('<h2 id="sheetTitle">병가 증빙 확인</h2><p class="prototype-note">신청기간과 증빙기간이 달라 자동 승인하지 않았습니다.</p><div class="detail-grid"><span>직원</span><span>직원 05</span><span>신청기간</span><span>8/10–8/14</span><span>증빙기간</span><span>8/10–8/12</span></div><div class="sheet-actions"><button data-sheet-action="request-document">추가 증빙 요청</button><button class="primary-action" data-sheet-action="edit-leave">기간 수정</button></div>');
    else openSheet('<h2 id="sheetTitle">지문 데이터 상태</h2><p class="prototype-note">현재 목업에서는 실제 단말이나 운영 DB에 연결하지 않습니다.</p><div class="detail-grid"><span>마지막 반영</span><span>오늘 08:20</span><span>수집 방식</span><span>USB 월간 XLS</span><span>상태</span><span>정상 · 데모</span></div>');
  }
  function renderPeople(query){
    query=(query||'').trim().toLowerCase();
    var filtered=people.filter(function(p){return !query||(p.name+' '+p.zone).toLowerCase().includes(query)});
    document.getElementById('peopleCount').textContent=filtered.length+'명';
    document.getElementById('peopleList').innerHTML=filtered.map(function(p){var cls=p.state==='확인'?'check':p.state==='휴가'?'absent':'ok';return '<button data-person="'+esc(p.name)+'"><span class="avatar">'+esc(p.id)+'</span><span><b>'+esc(p.name)+'</b><small>'+esc(p.zone)+' · '+esc(p.shift)+'</small></span><em class="status '+cls+'">'+esc(p.state)+'</em></button>'}).join('')||'<p class="prototype-note">검색 결과가 없습니다.</p>';
  }
  document.addEventListener('click',function(e){
    var nav=e.target.closest('[data-nav]');if(nav){go(nav.dataset.nav);return}
    var period=e.target.closest('[data-period]');if(period){setPeriod(period.dataset.period);return}
    var periodDay=e.target.closest('[data-period-day]');if(periodDay){setPeriod('day');window.scrollTo(0,0);return}
    var jump=e.target.closest('[data-go]');if(jump){go(jump.dataset.go);return}
    var person=e.target.closest('[data-person]');if(person){personSheet(person.dataset.person);return}
    var action=e.target.closest('[data-action]');if(action){actionSheet(action.dataset.action);return}
    var sheetAction=e.target.closest('[data-sheet-action]');if(sheetAction){closeSheet();showToast('목업에서 처리 흐름을 확인했습니다. 실제 저장은 하지 않습니다.');return}
    if(e.target.id==='cancelSheet'){closeSheet()}
  });
  document.getElementById('sheetClose').addEventListener('click',closeSheet);
  backdrop.addEventListener('click',function(e){if(e.target===backdrop)closeSheet()});
  document.getElementById('personSearch').addEventListener('input',function(e){renderPeople(e.target.value)});
  renderPeople('');
})();

