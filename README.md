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

공개되는 파일은 `index.html`, `profile.css`, `profile.js`, `.nojekyll` 뿐입니다.
백엔드(`app/`)와 운영 데이터(`data/`, `uploads/`, `backups/`)는 배포에 포함되지 않습니다.

> 모든 이름과 기록은 데모용 목데이터입니다. 실제 개인정보가 아닙니다.

---

## 백엔드 (Phase 1)

`AI_BUILD_PLAN.md` Phase 1 범위의 백엔드 골격입니다.
**현재 데모는 여전히 정적 페이지로 단독 동작하며, 프론트엔드는 아직 API에 연결되어 있지 않습니다.**

```
app/
  main.py          FastAPI 앱 (health 엔드포인트만)
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
python -m app.main             # 127.0.0.1:8000 에서 실행
curl http://127.0.0.1:8000/health
```

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
