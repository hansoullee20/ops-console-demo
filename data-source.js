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
  var state = { weekStart: null, today: null, fingerprint: null, dataContext: null };

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

    if (MODE === 'demo') {
      setBadge('공개 데모 · 가상 데이터 ' + employees.length + '명', '');
    } else if (state.dataContext === 'demo') {
      setBadge('데모 시드 DB · ' + fingerprintText(), '');
    } else {
      setBadge(fingerprintText(), 'live');
    }
  }

  // --- boot ---------------------------------------------------------------
  function bootDemo() {
    var snapshot = window.OPS_DEMO_SNAPSHOT;
    if (!snapshot) {
      showError('데모 스냅샷(demo-data.js)이 배포본에 포함되지 않았습니다.');
      return;
    }
    apply(snapshot);
  }

  function bootOperational() {
    showLoading();
    fetch(API_BASE + '/bootstrap', { headers: { Accept: 'application/json' } })
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
    if (MODE === 'demo') bootDemo();
    else bootOperational();
  };

  window.OPS_MODE_ACTIVE = MODE;

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
