# frontend/

이 디렉터리는 **의도적으로 비어 있습니다.**

## 결정 (Phase 2)

`index.html`, `profile.js`, `profile.css` 는 **저장소 루트에 그대로 둡니다.**
Phase 2 에서 `frontend/` 로 이동하지 않습니다.

이유:
Phase 2 의 위험은 DB/API/프론트엔드 데이터 흐름 통합에 집중되어야 합니다.
현재 GitHub Pages 배포는 실제 운영에서 검증이 끝난 상태이므로
(공개 4개 파일 200, 백엔드·운영 파일 404),
디렉터리 이동을 API 통합 작업과 한 PR 에 묶지 않습니다.

`frontend/` 이동이 여전히 바람직하다면 Phase 2 가 안정되고 독립 검증을 거친 뒤
**별도의 작은 PR** 로 처리합니다.

## 현재 배치

```
index.html        루트 — GitHub Pages 가 여기서 서빙
profile.css       루트
profile.js        루트
data-source.js    루트 — API/데모 모드 데이터 로딩
import-ui.js      루트 — 지문 XLS 가져오기 흐름 (데모 빌드에서는 안내만)
```

로컬 업무용 앱도 같은 파일을 FastAPI 가 화이트리스트로 서빙합니다
(`app/routers/frontend.py`). 로컬과 배포본의 HTML 동작은 동일합니다.

---

This directory is intentionally empty.

**Decision (Phase 2): keep `index.html`, `profile.js` and `profile.css` at the
repository root. Do not move the frontend into `frontend/` in this phase.**

Phase 2 should isolate risk to DB/API/frontend data-flow integration. The
current GitHub Pages deployment has already been verified in production, so a
directory migration is not combined with the API integration work.

If a `frontend/` move is still desirable, handle it later as a separate small
PR after Phase 2 is stable and independently verified.
