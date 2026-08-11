# frontend/

이 디렉터리는 **의도적으로 비어 있습니다.**

AI_BUILD_PLAN.md Phase 1 의 목표 구조에는 `frontend/` 가 있지만, 현재 공개 데모는
GitHub Pages 가 저장소 루트에서 서빙합니다:

```
index.html
profile.css
profile.js
```

이 파일들을 `frontend/` 로 옮기면 공개 데모 URL 이 바뀌고 현재 동작이 깨집니다.
Phase 1 규칙은 "현재 UI 와 데모 동작을 그대로 유지"이므로 이동하지 않았습니다.

이동은 Phase 2(백엔드 API 연결) 에서 배포 경로 변경과 함께 한 번에 처리하는 것이
안전합니다.

---

This directory is intentionally empty.

The Phase 1 target layout in `AI_BUILD_PLAN.md` includes `frontend/`, but the
public demo is served by GitHub Pages from the repository root. Moving
`index.html`, `profile.css` and `profile.js` here would change the live demo URL
and break current behavior, which Phase 1 explicitly forbids.

The move should happen in Phase 2, together with the deployment path change,
when the frontend starts consuming the backend API.
