/* Where the operations console gets its data.
 *
 * There are exactly two modes, and the mode is decided by the build, never by
 * a network outcome:
 *
 *   OPERATIONAL (default)  the API is the only source of truth. If it is
 *                          unavailable the app says so. It does NOT fall back
 *                          to the fictional snapshot — a backend outage must
 *                          never be able to put made-up staffing on screen.
 *
 *   DEMO                   the public GitHub Pages build. The deploy injects
 *                          window.OPS_MODE='demo' and the generated
 *                          demo-data.js. That file is not present on the work
 *                          PC at all, so operational mode cannot show demo
 *                          data even by accident.
 */
(function () {
  'use strict';

  var MODE = window.OPS_MODE === 'demo' ? 'demo' : 'operational';
  var API_BASE = '/api/v1';
  var state = { weekStart: null, today: null, fingerprint: null, dataContext: null, leave: [], monthGrid: null };

  // --- chrome -------------------------------------------------------------
  function badge() {
    return document.querySelector('header.top .demo');
  }

  function setBadge(text, tone) {
    var el = badge();
    if (!el) return;
    el.textContent = text;
    el.style.background = tone === 'error' ? '#fff1ef' : tone === 'live' ? '#edf7f1' : '';
    el.style.color = tone === 'error' ? '#a33a32' : tone === 'live' ? '#2c6846' : '';
    el.style.borderColor = tone === 'error' ? '#eac3bd' : tone === 'live' ? '#c6e3d2' : '';
  }

  function fingerprintText() {
    if (!state.fingerprint || !state.fingerprint.lastImportAt) {
      return '지문 데이터 기준: 없음';
    }
    return '지문 데이터 기준: ' + String(state.fingerprint.lastImportAt).slice(0, 16).replace('T', ' ');
  }

  var TARGETS = ['opsContent', 'attendanceGrid', 'employeeTable'];

  function paint(html) {
    TARGETS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.innerHTML = html;
    });
  }

  function showLoading() {
    setBadge('불러오는 중…', '');
    paint(
      '<section class="panel"><div class="panelhead"><h1>불러오는 중</h1></div>' +
        '<div style="padding:26px;color:#6d7682">서버에서 운영 데이터를 가져오고 있습니다…</div></section>'
    );
  }

  function showError(detail) {
    setBadge('데이터 없음 · 서버 연결 실패', 'error');
    var safe = String(detail || '').replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m];
    });
    paint(
      '<section class="panel"><div class="panelhead"><h1>운영 데이터를 불러오지 못했습니다</h1></div>' +
        '<div style="padding:26px;line-height:1.7">' +
        '<p style="margin:0 0 10px"><b>표시할 업무 데이터가 없습니다.</b> 화면의 수치를 근거로 배치나 근태를 판단하지 마십시오.</p>' +
        '<p style="margin:0 0 10px;color:#6d7682">백엔드에 연결하지 못했습니다. 예시 데이터로 대체하지 않습니다.</p>' +
        '<p style="margin:0 0 14px;color:#6d7682;font-size:12px">' + safe + '</p>' +
        '<button class="btn primary" onclick="window.OPS_RELOAD()">다시 시도</button>' +
        '</div></section>'
    );
  }

  // --- period title, derived from the loaded week -------------------------
  window.periodTitleFor = function (mode) {
    if (!days.length) return '';
    if (mode === 'daily') {
      var d = days[typeof selectedDay === 'number' ? selectedDay : 0] || days[0];
      var dow = String(d.dow).replace(' · 오늘', '');
      return monthOf() + '월 ' + d.num + '일 ' + dow + '요일';
    }
    if (mode === 'weekly') {
      return monthOf() + '월 ' + days[0].num + '일–' + days[days.length - 1].num + '일';
    }
    return yearOf() + '년 ' + monthOf() + '월';
  };

  function yearOf() {
    return state.weekStart ? Number(state.weekStart.slice(0, 4)) : new Date().getFullYear();
  }
  function monthOf() {
    return state.weekStart ? Number(state.weekStart.slice(5, 7)) : new Date().getMonth() + 1;
  }

  // --- rendering ----------------------------------------------------------
  function isMobile() {
    return window.matchMedia && window.matchMedia('(max-width: 760px)').matches;
  }

  function apply(payload) {
    days = payload.days || [];
    employees = payload.employees || [];
    monthStats = payload.monthStats || {};
    state.weekStart = payload.weekStart || null;
    state.today = payload.today || null;
    state.fingerprint = payload.fingerprint || null;
    state.leave = payload.leave || [];
    state.monthGrid = payload.monthGrid || null;
    state.dataContext = payload.dataContext || payload.mode || null;

    var todayIndex = -1;
    for (var i = 0; i < days.length; i++) {
      if (days[i].today) { todayIndex = i; break; }
    }
    if (todayIndex >= 0) selectedDay = todayIndex;

    // desktop defaults to the week, mobile to the day (approved Phase 2 change)
    opsMode = isMobile() ? 'daily' : 'weekly';

    renderOps();
    renderAttendance();
    renderEmployees();
    renderEmployeeBrief();
    renderLeave();
    renderAttendanceSummary();

    if (MODE === 'demo') {
      setBadge('공개 데모 · 가상 데이터 ' + employees.length + '명', '');
    } else if (state.dataContext === 'demo') {
      setBadge('데모 시드 DB · ' + fingerprintText(), '');
    } else {
      setBadge(fingerprintText(), 'live');
    }
  }


  // --- views that used to be hard-coded in index.html ---------------------
  // These read the same loaded payload as the grid, so every tab shows one
  // dataset. Previously the 휴가 tab, the daily sidebar and the employee
  // summary carried their own copies of the demo people.

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m];
    });
  }

  function shortDate(iso) {
    if (!iso) return '';
    var parts = String(iso).split('-');
    return parts.length === 3 ? Number(parts[1]) + '/' + Number(parts[2]) : iso;
  }

  var LEAVE_TAG = {
    sick: ['red', '병가'],
    annual: ['blue', '연차'],
    half_day: ['blue', '반차'],
    unpaid: ['gray', '무급'],
    special: ['purple', '특별'],
    other: ['gray', '기타']
  };
  var STATUS_TAG = {
    approved: ['green', '승인'],
    requested: ['amber', '승인대기'],
    draft: ['gray', '작성중'],
    rejected: ['gray', '반려'],
    cancelled: ['gray', '취소']
  };

  window.renderLeave = function () {
    var body = document.getElementById('leaveTable');
    var summary = document.getElementById('leaveSummary');
    if (!body || !summary) return;

    var cases = state.leave || [];
    var pending = 0, findings = 0, annualDays = 0;
    cases.forEach(function (c) {
      if (c.status === 'requested') pending++;
      if (c.finding) findings++;
      if (c.leaveType === 'annual' || c.leaveType === 'half_day') {
        annualDays += Number(c.workingDayCount || 0);
      }
    });

    summary.innerHTML =
      tile(cases.length, '진행중') + tile(pending, '승인대기') +
      tile(findings, '증빙 불일치') + tile(annualDays + '일', monthOf() + '월 연차');

    body.innerHTML = cases.map(function (c) {
      var kind = LEAVE_TAG[c.leaveType] || LEAVE_TAG.other;
      var st = c.finding ? ['red', '확인 필요'] : (STATUS_TAG[c.status] || STATUS_TAG.draft);
      var period = shortDate(c.startDate) + (c.endDate && c.endDate !== c.startDate ? '–' + shortDate(c.endDate) : '');
      var evidence = c.certStartDate
        ? '진단서 ' + shortDate(c.certStartDate) + '–' + shortDate(c.certEndDate)
        : '—';
      var attrs = c.finding
        ? ' class="issueRow" onclick="openGeneric(' +
          q(c.employee + ' · ' + kind[1]) + ',' + q(c.finding) + ',' +
          q('신청 ' + period + ' · 증빙 ' + evidence) + ',' +
          q('신청기간 또는 증빙기간을 확인해야 합니다.') + ')"'
        : '';
      return '<tr' + attrs + '>' +
        '<td><b>' + esc(c.employee) + '</b>' + (c.zone ? '<div class="sub">' + esc(c.zone) + '</div>' : '') + '</td>' +
        '<td><span class="tag ' + kind[0] + '">' + kind[1] + '</span></td>' +
        '<td>' + esc(period) + '</td>' +
        '<td>' + esc(c.workingDayCount == null ? '—' : c.workingDayCount + '일') + '</td>' +
        '<td>' + esc(evidence) + '</td>' +
        '<td><span class="tag ' + st[0] + '">' + st[1] + '</span></td></tr>';
    }).join('') || '<tr><td colspan="6" style="color:#6d7682;padding:22px">휴가 기록이 없습니다.</td></tr>';
  };

  function tile(value, label) {
    return '<div class="sum"><b>' + esc(value) + '</b><span>' + esc(label) + '</span></div>';
  }

  function q(text) {
    return "'" + String(text).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;') + "'";
  }

  // Called from renderDaily's template in index.html.
  window.dailyAside = function () {
    if (!employees.length) return '<aside class="dayaside"></aside>';
    var index = typeof selectedDay === 'number' ? selectedDay : 0;
    var counts = { planned: 0, issue: 0, sick: 0, replacement: 0 };
    var todo = [];
    employees.forEach(function (e) {
      var cell = e.cells[index];
      if (!cell) return;
      if (cell.type !== 'off') counts.planned++;
      if (cell.issue) { counts.issue++; todo.push({ name: e.name, label: cell.label }); }
      if (cell.type === 'sick') counts.sick++;
      if (cell.type === 'replacement') counts.replacement++;
    });
    return '<aside class="dayaside"><div class="statgrid">' +
      stat(counts.planned, '예정 인원') + stat(counts.issue, '확인 필요') +
      stat(counts.sick, '병가') + stat(counts.replacement, '대체') +
      '</div>' +
      (todo.length
        ? todo.map(function (t) {
            return '<div class="todoitem"><b>' + esc(t.name) + '</b><br>' + esc(t.label) + ' 확인</div>';
          }).join('')
        : '<div class="todoitem">확인할 항목이 없습니다.</div>') +
      '</aside>';
  };

  function stat(value, label) {
    return '<div class="stat"><b>' + esc(value) + '</b><span>' + esc(label) + '</span></div>';
  }

  window.renderEmployeeBrief = function () {
    var el = document.getElementById('empBrief');
    if (!el) return;
    var substitutes = employees.filter(function (e) { return e.state === '대체'; }).length;
    var onLeave = employees.filter(function (e) { return e.state === '병가'; }).length;
    el.innerHTML = '<b>재직자 ' + employees.length + '명</b> · 대체 ' + substitutes + '명 · 병가 ' + onLeave + '명';
  };


  // The 근태 tab used to paint marks from the row index (병 for row 0, 휴 for
  // row 4 …) for only the first ten people. It now renders every employee from
  // real attendance rows. A day with no record shows 기록 없음 — never 정, and
  // never absence: missing data is evidence of neither.
  window.renderAttendanceGrid = function () {
    var host = document.getElementById('attendanceGrid');
    if (!host) return;
    var grid = state.monthGrid;
    if (!grid || !grid.employees.length) {
      host.innerHTML = '<div style="padding:22px;color:#6d7682">근태 데이터가 없습니다.</div>';
      return;
    }
    var head = '<table><thead><tr><th>직원</th>';
    for (var d = 1; d <= grid.days; d++) head += '<th>' + d + '</th>';
    head += '<th>확인</th></tr></thead><tbody>';

    var body = grid.employees.map(function (row) {
      var tds = row.marks.map(function (mark, i) {
        var title = mark === '·' ? ' title="기록 없음"' : '';
        var muted = mark === '·' || mark === '—' ? ' style="color:#c3c9d0"' : '';
        return '<td' + muted + title + ' onclick="toast(' +
          q(row.name + ' · ' + grid.month + '/' + (i + 1)) + ')">' + esc(mark) + '</td>';
      }).join('');
      return '<tr><td><b>' + esc(row.name) + '</b></td>' + tds +
             '<td>' + row.issues + '</td></tr>';
    }).join('');

    host.innerHTML = head + body + '</tbody></table>' +
      '<div style="padding:10px 14px;color:#6d7682;font-size:12px">' +
      '정 출근 · 휴 휴가 · 병 병가 · ! 확인 필요 · ? 확인 불가 · — 비근무일 · · 기록 없음</div>';
  };


  // The 근태 tab's summary and its "이상" badge were fixed numbers in the HTML.
  // They are counted from the same month grid the table renders.
  window.renderAttendanceSummary = function () {
    var grid = state.monthGrid;
    var label = yearOf() + '년 ' + monthOf() + '월';
    ['attendanceMonth', 'leaveMonth'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.textContent = label;
    });

    var summary = document.getElementById('attendanceSummary');
    var badge = document.getElementById('attendanceIssueCount');
    if (!grid) {
      if (summary) summary.innerHTML = '';
      if (badge) badge.textContent = '0';
      return;
    }
    var counts = { '정': 0, '휴': 0, '병': 0, '!': 0, '?': 0 };
    grid.employees.forEach(function (row) {
      row.marks.forEach(function (mark) {
        if (counts[mark] !== undefined) counts[mark]++;
      });
    });
    if (summary) {
      summary.innerHTML =
        tile(grid.employees.length, '재직자') + tile(counts['정'], '정상 근무일') +
        tile(counts['휴'], '연차') + tile(counts['병'], '병가') +
        tile(counts['!'] + counts['?'], '확인 필요');
    }
    if (badge) badge.textContent = String(counts['!'] + counts['?']);
  };

  // --- boot ---------------------------------------------------------------
  function bootDemo() {
    var snapshot = window.OPS_DEMO_SNAPSHOT;
    if (!snapshot) {
      showError('데모 스냅샷(demo-data.js)이 배포본에 포함되지 않았습니다.');
      return Promise.resolve();
    }
    apply(snapshot);
    return Promise.resolve();
  }

  function bootOperational() {
    var aiButton = document.querySelector('.ai-fab');
    var aiPanel = document.getElementById('aiWrap');
    if (aiButton) aiButton.hidden = true;
    if (aiPanel) aiPanel.hidden = true;
    showLoading();
    return fetch(API_BASE + '/bootstrap', { headers: { Accept: 'application/json' } })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status + ' ' + res.statusText);
        return res.json();
      })
      .then(function (payload) {
        // Guard the invariant at the boundary too: demo data must never be
        // rendered as operational data.
        if (payload && payload.mode === 'demo') {
          throw new Error('API returned demo-mode data; refusing to render it as operational');
        }
        apply(payload);
      })
      .catch(function (err) {
        showError(err && err.message ? err.message : String(err));
      });
  }

  window.OPS_RELOAD = function () {
    if (MODE === 'demo') return bootDemo();
    return bootOperational();
  };

  window.OPS_MODE_ACTIVE = MODE;

  // The single demo-mode decision. Every UI file asks this instead of reading a
  // global of its own choosing: safety-ui.js and month-close-ui.js each guarded
  // on `window.OPS_DATA_MODE`, which nothing has ever set, so their guards were
  // dead and the public demo called the operational API for months. A guard
  // that reads the wrong name looks correct in review and fails silently.
  window.OPS_IS_DEMO = function () {
    return MODE === 'demo';
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.OPS_RELOAD);
  } else {
    window.OPS_RELOAD();
  }

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    if (!employees.length) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      var wanted = isMobile() ? 'daily' : 'weekly';
      if (opsMode !== 'monthly' && opsMode !== wanted) {
        opsMode = wanted;
        renderOps();
      }
    }, 150);
  });
})();
