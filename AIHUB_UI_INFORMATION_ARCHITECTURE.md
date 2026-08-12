# AI Hub / Okja — Product UI Information Architecture v0.1

Date: 2026-08-12
Status: structure before visual styling

## Product rule

Okja is one adaptive product, not separate grandmother and personal apps. The interaction grammar stays stable; speaker/user identity, room/device identity, permissions and preferences change what content is surfaced.

Okja is **voice-first, touch-second**. The display communicates state, gives glanceable information, and provides a simple fallback when voice is inconvenient.

## Shared state machine

1. AMBIENT_HOME — glanceable information, no conversational chrome.
2. LISTENING — unmistakable microphone/listening state and recognized partial text when useful.
3. THINKING_EXECUTING — short action/status phrase; never an indefinite spinner with no explanation.
4. RESULT — answer/action result, with at most one or two obvious follow-up actions.
5. MANUAL_DASHBOARD — touch fallback for common actions.
6. MIC_OFF — persistent, unmistakable privacy state.
7. OFFLINE_DEGRADED — clearly show what still works locally.
8. ERROR_RECOVERY — plain-language recovery action.

## Senior / grandmother presentation

### Goals
- readable from several feet away;
- minimal cognitive load;
- no dense tablet-dashboard appearance;
- large typography and large touch targets;
- very few simultaneous choices;
- predictable placement and wording;
- critical family/help actions always easy to recover.

### Ambient home priority
1. Large time.
2. Date/day.
3. Weather/current condition only if useful.
4. Next important reminder/medication/event.
5. Small family/status area only when something needs attention.

Avoid permanent grids of many cards. The idle screen should remain calm.

### Manual dashboard priority
Maximum initial target: 4–6 large actions, subject to user research.
Candidate actions:
- 가족 / 전화
- TV
- 오늘 일정 / 약
- 날씨
- 도움 요청
- 설정 (de-emphasized; may require long press or secondary screen)

### Senior readability constraints to validate
- large default type, especially time and primary action labels;
- high contrast;
- no information conveyed by color alone;
- minimum comfortable touch targets larger than standard phone UI;
- avoid icon-only controls for important actions;
- avoid gesture-only navigation;
- one obvious primary action on transient/result screens.

## Personal presentation

Same state machine and design language, but higher information density is allowed.

### Ambient home candidate hierarchy
1. Time/date/weather.
2. Today's schedule and next event.
3. Tasks/reminders.
4. Context-aware device/home status.
5. Personal device finding / quick actions.
6. Relevant messages/notifications only when actionable.

The personal home should not become a generic notification center. Prefer a few high-value cards selected by context.

### Manual dashboard candidates
- 일정
- 할 일
- 내 기기 찾기
- 집 / 방 제어
- 음악 / 미디어
- 메시지 / 가족
- settings/profile

## Shared wake interaction

Example:

AMBIENT_HOME
→ user says wake phrase
→ LISTENING: simple listening indicator + “듣고 있어요”
→ recognized command can appear as large text
→ THINKING_EXECUTING: e.g. “휴대폰을 찾는 중”
→ RESULT: e.g. “휴대폰을 울릴게요” + one obvious Cancel action
→ return to AMBIENT_HOME

Do not expose model names, agent routing or technical backend status to normal users.

## Privacy / microphone UX

Always-listening behavior requires visible trust signals.
- MIC_OFF must look materially different from normal ambient mode.
- Listening state must be visually unmistakable.
- If hardware permits, pair UI state with a physical microphone control/indicator.
- Local wake listening and cloud command processing should be distinguishable in settings/help, without cluttering normal interaction.

## What is deliberately NOT decided yet
- colors/brand palette;
- final icon family;
- animation language;
- exact card styling;
- final typography family;
- final home-card count;
- portrait behavior;
- final accessibility sizes.

These should follow mockup/usability evaluation, not precede it.

## First mockup set

Create on a 7-inch-class landscape smart-display frame:
1. Senior AMBIENT_HOME.
2. Senior MANUAL_DASHBOARD.
3. Personal AMBIENT_HOME.
4. Shared LISTENING.
5. Shared THINKING_EXECUTING.
6. Shared RESULT.
7. MIC_OFF / OFFLINE variants.

Evaluate senior screens first at realistic viewing distance, not only enlarged on a desktop monitor.
