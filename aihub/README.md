# AI Hub Voice Test

테스트 목표:

`Android SpeechRecognizer → persistent Claude Agent SDK → Android TTS`

## 프로필

### 할머니용 — 옥자
- 표시 이름: `옥자`
- 입력 언어: `ko-KR` 고정
- STT: Android 기본 음성인식 서비스, 한국어 locale 강제
- Claude: `haiku`
- 응답 스타일: 짧고 쉬운 한국어 존댓말, 음성 청취 우선

### 개인용 — AI Hub
- 표시 이름: `AI Hub`
- 입력 언어: `ko-KR` / `en-US` 전환
- Claude: `sonnet`
- 응답 스타일: 간단한 질문은 짧게, 복잡한 질문은 더 충분히 추론

현재 테스트 APK에서는 프로필과 개인용 입력 언어를 버튼으로 전환한다. 실제 기기 2대를 만들 때는 각 기기에서 프로필을 고정할 예정이다.

## 폰의 Ubuntu 브리지

기존 `~/claude-sdk` 환경과 Claude Code 로그인이 되어 있다는 전제다.

이 저장소의 `phone/aihub_bridge.py`를 Ubuntu의 `/root/aihub_bridge.py`로 복사한 뒤:

```bash
source ~/claude-sdk/bin/activate
python ~/aihub_bridge.py
```

정상이면:

```text
[AI Hub] Grandma profile ready: 옥자 / ko-KR / haiku
[AI Hub] Personal profile ready: AI Hub / ko-KR+en-US / sonnet
[AI Hub] listening on ('127.0.0.1', 8765)
```

## APK 빌드

GitHub Actions의 `Build AI Hub test APK` workflow가 `aihub/app`을 빌드한다.

Artifact 이름:

```text
aihub-dual-profile-debug-apk
```

설치 후 마이크 권한을 허용하고 `말하기`를 누른다.

## 아직 제외한 기능

- wake word 상시감지
- 자동 한국어/영어 판별
- GPT/Codex fallback
- 카메라
- 홈 자동화/MCP
- 부팅 후 자동 실행
- 저사양 태블릿 RAM/CPU 최적화

먼저 두 프로필의 STT → Claude → TTS 왕복과 실제 지연시간을 검증한다.
