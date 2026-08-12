# AI Hub / Okja voice project

> **Working branch:** `aihub-voice-test`  
> **Project directory:** `aihub/`  
> **Handoff / restart guide:** [`AIHUB_HANDOFF.md`](./AIHUB_HANDOFF.md)

This branch contains the Android AI Hub / **옥자 (Okja)** voice-assistant prototype. The current end-to-end path is Android STT → persistent Claude Agent SDK bridge → Android TTS, with a working wake-phrase prototype and an active migration toward a fully free/local wake backend.

If you are resuming this project in a new ChatGPT/Claude/Codex session, **read `AIHUB_HANDOFF.md` first**.

---

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

> 모든 이름과 기록은 데모용 목데이터입니다. 실제 개인정보가 아닙니다.
