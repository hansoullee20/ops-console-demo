# 대학 미화 운영 공개 데모

대학 미화 인력 운영 콘솔의 공개 목데이터 데모입니다.

## 특징
- 18명 목데이터 내장
- 운영 Daily / Weekly / Monthly
- 근태 / 휴가 / 직원 / 문서 탭
- 상세 drawer
- AI 목채팅
- PC/모바일 반응형
- 서버/DB/API 없이 정적 페이지로 동작

## GitHub Pages
Settings → Pages → Deploy from a branch → `main` / `(root)` 로 설정하면 공개 URL로 실행할 수 있습니다.

공개되는 파일은 `index.html`, `profile.css`, `profile.js`, `data-source.js`,
배포 시 생성되는 `demo-data.js`, `.nojekyll` 뿐입니다.
백엔드(`app/`)와 운영 데이터(`data/`, `uploads/`, `backups/`)는 배포에 포함되지 않습니다.

> 모든 이름과 기록은 데모용 목데이터입니다. 실제 개인정보가 아닙니다.

---

## 백엔드 (Phase 2)

`AI_BUILD_PLAN.md` Phase 2 범위입니다. UI는 그대로 두고 데이터 출처를 백엔드 하나로 모았습니다.

**모드는 빌드가 결정하며, 네트워크 실패가 결정하지 않습니다.**

| | 데이터 출처 | 실패 시 |
|---|---|---|
| 로컬/업무용 | FastAPI API | 오류 화면. 가상 데이터로 대체하지 않음 |
| GitHub Pages 공개 데모 | 배포 시 생성된 스냅샷 | — (백엔드 없음) |

`demo-data.js`는 배포 시점에 정본 시드에서 생성되며 저장소에 커밋되지 않습니다.
업무용 호스트에는 이 파일이 존재하지 않으므로, 백엔드가 죽어도 가상 데이터가 나타날 수 없습니다.

```
app/
  main.py          FastAPI 앱 (health + 읽기 전용 API + UI 서빙)
  routers/api.py   /api/v1/* 읽기 API
  routers/frontend.py  루트 프론트엔드 화이트리스트 서빙
  seed/            정본 가상 데이터셋 + 시더
  exporters/       배포용 데모 스냅샷 생성
  config.py        경로/설정 (환경변수로 override)
  db.py            SQLite 연결 (항상 foreign_keys=ON)
  migrate.py       멱등 + 백업 마이그레이션 러너
  migrations/      NNNN_이름.sql
  models/ schemas/ services/ rules/ routers/
  tests/
data/              SQLite 파일 (git 제외)
uploads/           업로드 원본 (git 제외)
backups/           마이그레이션 전 스냅샷 (git 제외)
```

### 실행

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m app.migrate          # DB 생성 / 마이그레이션 (재실행 안전)
python -m app.seed             # 가상 데이터 시딩 (data_context=demo 로 표시됨)
python -m app.main             # 127.0.0.1:8000 에서 실행
```

브라우저로 `http://127.0.0.1:8000/` 을 열면 콘솔이 뜹니다.
API 는 `/api/v1/bootstrap`, 상태는 `/health` 입니다.

기본 bind 주소는 루프백입니다. 백엔드와 SQLite는 인터넷에 직접 노출하지 않습니다.

### 테스트

```bash
python -m pytest
```

### 데이터 규칙 (스키마에서 강제)

- `attendance_days` 는 `(employee_id, work_date)` 유일
- `punch_events` 는 원본 불변: DELETE 금지, 원본 컬럼 UPDATE 금지 (트리거)
- 재태그 후보는 플래그만 남기고 원본은 보존
- 대체 배정은 별도 테이블이라 정상 근태를 덮어쓰지 않음
- `audit_log` 는 append-only
- 마이그레이션은 멱등이며, 기존 DB 변경 전 자동 백업
- 파괴적 마이그레이션은 명시적 마커 없이는 거부됨
- 근태 수정은 `app/services/attendance.py` 의 `correct_attendance()` 만 사용
  (`id`/`created_at` 유지, `revision` +1, 같은 트랜잭션 `audit_log`).
  `attendance_days`/`leave_balances`/`terminal_slots` 에
  `INSERT OR REPLACE` / `REPLACE INTO` / `UPDATE OR REPLACE` 금지 — 테스트로 강제됨
