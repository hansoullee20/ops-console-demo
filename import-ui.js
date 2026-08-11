/* 지문 XLS 가져오기 — the operator-facing side of Phase 3.
 *
 * The flow is four deliberate steps, and the third one cannot be skipped:
 *
 *     파일 선택  →  미리보기  →  확인  →  적용        (+ 롤백)
 *
 * The preview writes nothing. Applying requires the token that preview issued,
 * so a mis-click cannot import a month of attendance; and the confirm step
 * shows what will change *before* anything is written, because the operator is
 * the last check on a wrong file.
 *
 * In the public demo build there is no backend, so the button explains that
 * instead of pretending to work. It never fabricates a result.
 */
(function () {
  'use strict';

  var API = '/api/v1/imports';
  var current = null;   // the preview being reviewed
  var applied = null;   // the result of the last apply, for 롤백

  function el(id) { return document.getElementById(id); }

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m];
    });
  }

  function drawer(title, sub, body, foot) {
    el('dtitle').textContent = title;
    el('dsub').textContent = sub || '';
    el('dbody').innerHTML = body;
    el('dfoot').innerHTML = foot || '<button class="btn" onclick="closeDrawer()">닫기</button>';
    el('drawerWrap').classList.add('open');
  }

  function isDemo() {
    return window.OPS_MODE_ACTIVE === 'demo';
  }

  function demoNotice() {
    drawer(
      '지문 XLS 가져오기',
      '공개 데모',
      '<div class="box"><div class="kv">' +
        '<div class="k">상태</div><div>이 페이지는 <b>공개 데모</b>이며 백엔드가 없습니다.</div>' +
        '<div class="k">가져오기</div><div>실제 지문 기록 가져오기는 업무용 PC에서 실행되는 ' +
        '백엔드에서만 동작합니다.</div>' +
        '<div class="k">이유</div><div>가상 직원 데이터에 실제 근태 기록을 섞지 않기 위해서입니다.</div>' +
      '</div></div>'
    );
  }

  function fail(message, detail) {
    drawer('가져오기 실패', '',
      '<div class="alert"><b>' + esc(message) + '</b>' +
      (detail ? '<br>' + esc(detail) : '') + '</div>' +
      '<p style="color:#6d7682;margin-top:12px">근태 데이터는 변경되지 않았습니다.</p>');
  }

  function detailOf(payload, res) {
    if (payload && payload.detail) {
      if (typeof payload.detail === 'string') return payload.detail;
      try { return JSON.stringify(payload.detail); } catch (e) { return String(payload.detail); }
    }
    return 'HTTP ' + res.status + ' ' + res.statusText;
  }

  function send(url, options) {
    return fetch(url, options).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (payload) {
        if (!res.ok) {
          var err = new Error(detailOf(payload, res));
          err.status = res.status;
          throw err;
        }
        return payload;
      });
    });
  }

  // --- step 1: pick a file ---------------------------------------------------
  window.OPS_OPEN_IMPORT = function () {
    if (isDemo()) return demoNotice();
    current = null;
    applied = null;
    drawer('지문 XLS 가져오기', '1단계 · 파일 선택',
      '<div class="box"><div class="kv">' +
        '<div class="k">파일</div><div><input type="file" id="importFile" accept=".xls,.XLS"></div>' +
        '<div class="k">형식</div><div>지문 단말이 내보낸 월별 <b>.XLS</b> 파일</div>' +
      '</div></div>' +
      // The app cannot reach the terminal: the operator exports the month from
      // the terminal's own PC program first. Saying so here, because a blank
      // file picker does not tell anyone where the file is supposed to come from.
      '<p style="color:#6d7682;margin-top:12px;line-height:1.7">' +
      '<b>파일은 지문 단말 관리 프로그램에서 먼저 내려받아야 합니다.</b> ' +
      '프로그램에서 해당 월을 조회한 뒤 <b>내보내기(Export)</b> 로 저장한 <b>.XLS</b> 파일을 ' +
      '여기에서 선택하십시오. 이 앱은 단말에 직접 접속하지 않습니다.</p>' +
      '<p style="color:#6d7682;margin-top:10px;line-height:1.7">' +
      '먼저 <b>미리보기</b>만 실행합니다. 이 단계에서는 근태 데이터가 전혀 바뀌지 않으며, ' +
      '무엇이 들어오는지 확인한 뒤에만 적용됩니다.</p>',
      '<button class="btn" onclick="closeDrawer()">취소</button>' +
      '<button class="btn primary" onclick="OPS_IMPORT_PREVIEW()">미리보기</button>');
  };

  // --- step 2: preview -------------------------------------------------------
  window.OPS_IMPORT_PREVIEW = function () {
    var input = el('importFile');
    if (!input || !input.files || !input.files.length) {
      return window.toast('파일을 선택하십시오.');
    }
    var form = new FormData();
    form.append('file', input.files[0]);
    drawer('지문 XLS 가져오기', '2단계 · 읽는 중',
      '<p style="padding:8px 0;color:#6d7682">파일을 읽고 있습니다…</p>', '');

    send(API, { method: 'POST', body: form })
      .then(function (preview) {
        current = preview;
        showPreview(preview);
      })
      .catch(function (err) { fail('파일을 가져오지 못했습니다.', err.message); });
  };

  var SEVERITY = { blocking: ['red', '차단'], review: ['amber', '확인'], info: ['gray', '참고'] };

  function findingRows(findings) {
    if (!findings.length) return '<p style="color:#6d7682">확인할 항목이 없습니다.</p>';
    return '<table><thead><tr><th>구분</th><th>대상</th><th>내용</th></tr></thead><tbody>' +
      findings.map(function (f) {
        var sev = SEVERITY[f.severity] || SEVERITY.info;
        var who = [f.employee || f.slot, f.workDate].filter(Boolean).join(' · ');
        return '<tr><td><span class="tag ' + sev[0] + '">' + sev[1] + '</span></td>' +
          '<td>' + esc(who || '—') + '</td><td>' + esc(f.detail) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  function showPreview(p) {
    var slots = p.slots.filter(function (s) { return s.punchCount > 0; });
    var unmapped = slots.filter(function (s) { return s.status === 'unmapped'; }).length;
    var zero = (p.zeroPunchDates || []).length;
    var blocking = p.findings.filter(function (f) { return f.severity === 'blocking'; }).length;
    var review = p.findings.filter(function (f) { return f.severity === 'review'; }).length;

    var body =
      '<div class="box"><div class="kv">' +
        '<div class="k">파일</div><div>' + esc(p.sourceFilename) + '</div>' +
        '<div class="k">기간</div><div>' + esc(p.periodStart) + ' ~ ' + esc(p.periodEnd) +
          ' <span class="sub">(' + (p.coveredDates || []).length + '일 포함)</span></div>' +
        '<div class="k">새 기록</div><div><b>' + p.newPunches + '</b>건' +
          (p.alreadyImported ? ' <span class="sub">· 이미 가져온 기록 ' + p.alreadyImported + '건</span>' : '') +
          '</div>' +
        '<div class="k">사용 슬롯</div><div>' + slots.length + '개' +
          (unmapped ? ' <span class="tag amber">직원 미연결 ' + unmapped + '</span>' : '') + '</div>' +
        '<div class="k">확인 필요</div><div>' + review + '건' +
          (blocking ? ' <span class="tag red">차단 ' + blocking + '</span>' : '') + '</div>' +
      '</div></div>';

    if (zero) {
      // The full list can be most of a month; showing all of it would push the
      // confirm step off the screen. The count is the part that matters.
      var shown = (p.zeroPunchDates || []).slice(0, 10);
      var rest = zero - shown.length;
      body += '<div class="alert"><b>전 사업장 무기록 ' + zero + '일</b><br>' +
        esc(shown.join(', ')) + (rest > 0 ? ' 외 ' + rest + '일' : '') + '<br>' +
        '파일에 해당 날짜가 있는데 펀치가 하나도 없습니다. 휴무·단말 장애·부분 export 중 ' +
        '무엇인지는 사람이 확인해야 하며, <b>전원 결근으로 처리하지 않습니다.</b></div>';
    }

    body += '<h3 style="margin:18px 0 8px">슬롯</h3><div class="box" style="overflow-x:auto"><table>' +
      '<thead><tr><th>슬롯</th><th>직원</th><th>펀치</th><th>일수</th></tr></thead><tbody>' +
      slots.map(function (s) {
        var tag = s.status === 'unmapped' ? '<span class="tag amber">미연결</span>'
          : s.status === 'inactive' ? '<span class="tag red">비재직</span>'
          : esc(s.employee || '—');
        return '<tr><td>' + esc(s.slot) + '</td><td>' + tag + '</td>' +
          '<td>' + s.punchCount + '</td><td>' + s.dayCount + '</td></tr>';
      }).join('') + '</tbody></table></div>';

    body += '<h3 style="margin:18px 0 8px">확인 항목 ' + p.findings.length + '건</h3>' +
      '<div class="box" style="max-height:280px;overflow:auto">' + findingRows(p.findings) + '</div>';

    var foot;
    if (!p.canApply) {
      body += '<div class="alert" style="margin-top:14px"><b>적용할 수 없습니다.</b><br>' +
        (blocking ? '차단 항목을 먼저 해결해야 합니다.' : '새로 가져올 기록이 없습니다.') + '</div>';
      foot = '<button class="btn" onclick="closeDrawer()">닫기</button>';
    } else {
      body += '<label style="display:flex;gap:8px;align-items:flex-start;margin-top:16px">' +
        '<input type="checkbox" id="importConfirm" style="margin-top:3px">' +
        '<span>위 내용을 확인했으며, 이 파일의 기록 <b>' + p.newPunches + '건</b>을 ' +
        '근태 데이터에 반영합니다.</span></label>';
      foot = '<button class="btn" onclick="closeDrawer()">취소</button>' +
        '<button class="btn primary" onclick="OPS_IMPORT_APPLY()">적용</button>';
    }
    drawer('가져오기 미리보기', '3단계 · 확인 (아직 아무것도 저장되지 않았습니다)', body, foot);
  }

  // --- step 3/4: confirm and apply ------------------------------------------
  window.OPS_IMPORT_APPLY = function () {
    if (!current) return;
    var check = el('importConfirm');
    if (!check || !check.checked) return window.toast('확인란을 체크해야 적용됩니다.');

    drawer('적용 중', '', '<p style="padding:8px 0;color:#6d7682">근태 데이터에 반영하고 있습니다…</p>', '');
    send(API + '/' + current.importRunId + '/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmationToken: current.confirmationToken })
    })
      .then(function (result) {
        applied = result;
        drawer('가져오기 완료', current.sourceFilename,
          '<div class="box"><div class="kv">' +
            '<div class="k">추가된 기록</div><div><b>' + result.inserted + '</b>건</div>' +
            '<div class="k">이미 있던 기록</div><div>' + result.alreadyPresent + '건' +
              (result.reactivated ? ' <span class="sub">(롤백 복구 ' + result.reactivated + '건)</span>' : '') +
              '</div>' +
            '<div class="k">근태 갱신</div><div>' + result.attendanceRows + '일</div>' +
          '</div></div>' +
          '<p style="color:#6d7682;margin-top:12px;line-height:1.7">' +
          '적용 직전 데이터베이스 스냅샷을 저장했습니다. 잘못 가져왔다면 아래 되돌리기를 ' +
          '누르십시오. 원본 지문 기록은 어떤 경우에도 삭제되지 않습니다.</p>',
          '<button class="btn" onclick="OPS_IMPORT_ROLLBACK()">되돌리기</button>' +
          '<button class="btn primary" onclick="closeDrawer();window.OPS_RELOAD()">화면 갱신</button>');
      })
      .catch(function (err) { fail('적용하지 못했습니다.', err.message); });
  };

  window.OPS_IMPORT_ROLLBACK = function (runId) {
    var id = runId || (applied && applied.importRunId);
    if (!id) return;
    var reason = window.prompt('되돌리는 이유를 입력하십시오. (감사 기록에 남습니다)');
    if (!reason || !reason.trim()) return;

    send(API + '/' + id + '/rollback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason.trim() })
    })
      .then(function (result) {
        var conflicts = result.conflicts || [];
        drawer('되돌리기 완료', 'import #' + id,
          '<div class="box"><div class="kv">' +
            '<div class="k">되돌린 기록</div><div>' + result.punchesMarkedRolledBack + '건' +
              ' <span class="sub">(삭제 ' + result.punchesDeleted + '건)</span></div>' +
            '<div class="k">근태 재계산</div><div>' + result.attendanceRecomputed + '일</div>' +
          '</div></div>' +
          (conflicts.length
            ? '<div class="alert" style="margin-top:14px"><b>되돌리지 않은 항목 ' + conflicts.length + '건</b><br>' +
              '관리자가 확정했거나 이후 수정된 근태입니다. 사람이 확인해야 합니다.</div>' +
              '<div class="box" style="margin-top:10px;max-height:240px;overflow:auto">' +
              findingRows(conflicts) + '</div>'
            : ''),
          '<button class="btn primary" onclick="closeDrawer();window.OPS_RELOAD()">화면 갱신</button>');
        applied = null;
      })
      .catch(function (err) { fail('되돌리지 못했습니다.', err.message); });
  };

  // --- 원본기록: the import history -----------------------------------------
  var RUN_STATUS = {
    pending: ['gray', '업로드됨'], previewed: ['amber', '미리보기'],
    applied: ['green', '적용됨'], failed: ['red', '실패'], rolled_back: ['gray', '되돌림']
  };

  window.OPS_OPEN_IMPORT_HISTORY = function () {
    if (isDemo()) return demoNotice();
    drawer('원본 지문기록', '', '<p style="padding:8px 0;color:#6d7682">불러오는 중…</p>', '');
    send(API, { headers: { Accept: 'application/json' } })
      .then(function (runs) {
        if (!runs.length) {
          return drawer('원본 지문기록', '',
            '<p style="color:#6d7682">가져온 파일이 없습니다.</p>');
        }
        var rows = runs.map(function (r) {
          var st = RUN_STATUS[r.status] || RUN_STATUS.pending;
          var period = r.periodStart ? esc(r.periodStart) + ' ~ ' + esc(r.periodEnd) : '—';
          var undo = r.status === 'applied'
            ? '<button class="btn" onclick="OPS_IMPORT_ROLLBACK(' + r.id + ')">되돌리기</button>'
            : '';
          return '<tr><td><b>' + esc(r.sourceFilename || '—') + '</b>' +
              '<div class="sub">#' + r.id + ' · ' + period + '</div></td>' +
            '<td><span class="tag ' + st[0] + '">' + st[1] + '</span>' +
              (r.errorMessage ? '<div class="sub">' + esc(r.errorMessage) + '</div>' : '') + '</td>' +
            '<td>' + (r.punchEventCount == null ? '—' : r.punchEventCount) +
              '<div class="sub">' + r.coveredDays + '일</div></td>' +
            '<td>' + undo + '</td></tr>';
        }).join('');
        drawer('원본 지문기록', '가져온 파일은 원본 그대로 보관됩니다',
          '<div class="box" style="overflow-x:auto"><table><thead><tr><th>파일 · 기간</th>' +
          '<th>상태</th><th>기록</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
          '<p style="color:#6d7682;margin-top:12px;line-height:1.7">' +
          '원본 파일은 업무용 PC의 uploads 폴더에 보관되며 화면으로 내려받지 않습니다.</p>');
      })
      .catch(function (err) { fail('가져오기 기록을 불러오지 못했습니다.', err.message); });
  };
})();
