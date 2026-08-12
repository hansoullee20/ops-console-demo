# AI Hub / Okja — Product UI Information Architecture v0.3

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
9. NIGHT_AMBIENT — screen dark/minimal while wake listening stays active if enabled.
10. WELLNESS_CHECKIN — occasional low-pressure conversational health/wellbeing check-in.
11. EMERGENCY_CONFIRM / EMERGENCY_ACTION — simplified high-priority safety flow.

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
2. Large date/day.
3. Solar and lunar calendar date where configured.
4. Weather/current condition only if useful.
5. Next important reminder/medication/event.
6. Small family/status area only when something needs attention.

Avoid permanent grids of many cards. The idle screen should remain calm.

### Manual dashboard priority
Maximum initial target: 4–6 large actions, subject to user research.
Candidate actions:
- 가족 / 전화
- TV
- 오늘 일정 / 약
- 내 휴대폰 찾기
- 건강 이야기
- 도움 요청
- 설정 (de-emphasized; may require long press or secondary screen)

**Phone finding is a senior feature too, not personal-only.** It should be available by voice and as a large touch action. Default behavior can ring the registered phone, with a simple cancel state and clear failure message if the phone is offline/unreachable.

### TV / media flow
TV should not expose a complicated app launcher. Selecting TV opens a few large, personalized choices such as:
- continue a frequently watched Netflix program;
- show 3 simple recommendations;
- open favorite live-TV channels;
- news;
- frequently watched YouTube content;
- simply turn on the TV / resume the last source.

The exact services and titles are profile-driven and should not be hard-coded product-wide.

### Home-device control roadmap
Initial device control scope is deliberately small:
- TV;
- air conditioner.

Later expansion candidate:
- washing machine: connection/status, cycle selection where supported, completion notification, and simple error/status messaging.

Do not expose unsupported appliance actions until the specific device integration can confirm them reliably.

### Senior readability constraints to validate
- large default type, especially time, date and primary action labels;
- high contrast;
- no information conveyed by color alone;
- minimum comfortable touch targets larger than standard phone UI;
- avoid icon-only controls for important actions;
- avoid gesture-only navigation;
- one obvious primary action on transient/result screens.

## Wellness check-in and symptom history

Okja may occasionally initiate a gentle, optional check-in such as “오늘 몸은 좀 어떠세요?” or ask about a previously mentioned discomfort. This is a wellness/conversation feature, not medical diagnosis.

Rules:
- frequency must be configurable and easy to silence;
- never nag repeatedly after dismissal;
- ask one question at a time;
- keep follow-up short unless the user wants to talk;
- record only user-reported symptoms/status with timestamp and context;
- distinguish subjective reports from measured sensor data;
- allow family sharing only under configured consent/policy;
- repeated or worsening symptoms may prompt “가족에게 알려드릴까요?” rather than diagnose.

Example stored event:
- 2026-08-12 09:10 — user said “오늘 무릎이 좀 쑤셔.”
- category: self-reported discomfort
- sharing: local/private unless configured otherwise

## Night / dark behavior

Night behavior is more important than a cosmetic dark theme.

Proposed levels:
1. DAY — normal ambient UI.
2. NIGHT_DIM — dark background, very low brightness, only time/date/status.
3. SCREEN_OFF_LISTENING — display off or near-black after configured hours while local wake listening remains active if the user allows it.

Wake or touch may temporarily restore a low-brightness interface. MIC_OFF remains distinct from “screen dark but microphone listening.”

## Emergency flow

Emergency UI must be much simpler than normal navigation.

Initial emergency screen:
- very large “119에 연락” action;
- very large “가족에게 알리기” action;
- clear “괜찮아요 / 잘못 눌렀어요” exit;
- full voice equivalence for the same actions.

Configurable emergency family group may include several people (e.g. children, grandchildren, siblings). A family alert should carry only the minimum useful context: device/person, timestamp, location/device room, triggering request/event and whether emergency calling was initiated.

Korean deployment should offer onboarding guidance for official 119 안심콜 registration where appropriate. Automated emergency escalation must be validated separately from the UI; the UI mockup does not imply that unattended automatic emergency calling is already approved or implemented.

## Care / safety roadmap — deliberately staged

Do not make v1 a surveillance/medical system.

### Care v1 — conversation and explicit actions
- wellness check-ins;
- timestamped user-reported symptom history;
- medication/event reminders;
- family calling/messaging;
- phone finding;
- emergency UI and emergency-contact configuration;
- 119 안심콜 setup guidance.

### Care v2 — simple activity events
- optional camera/sensor-derived home/away or entry/exit events;
- long period with no normal activity as a low-confidence “please check” signal;
- privacy-first event storage; default to events rather than continuous video retention.

### Care v3 — night/activity sensing
- optional nighttime awakenings / bathroom-trip estimation;
- prefer privacy-preserving sensors where possible;
- show trends rather than medical conclusions.

### Care v4 — fall / emergency sensing
- camera or sensor fall-suspicion model;
- first ask “괜찮으세요?” where possible;
- combine multiple signals and user response before escalation;
- configurable family escalation and emergency-call handling;
- false-positive rate must be measured before unattended escalation is considered.

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
- Camera-based care features are opt-in, must expose camera state, and should prefer event metadata over continuous retained video.

## What is deliberately NOT decided yet
- colors/brand palette;
- final icon family;
- animation language;
- exact card styling;
- final typography family;
- final home-card count;
- portrait behavior;
- final accessibility sizes;
- exact sensor package for night/fall/activity features;
- automatic emergency-call policy.

These should follow mockup/usability evaluation, safety validation and real-device testing, not precede them.

## Current mockup set

7-inch-class landscape smart-display frame:
1. Senior AMBIENT_HOME with large solar/lunar date.
2. Senior TV/media choice flow.
3. Senior WELLNESS_CHECKIN.
4. Senior symptom-history example.
5. Senior NIGHT_AMBIENT.
6. Senior EMERGENCY_CONFIRM/ACTION.
7. Shared LISTENING / THINKING / RESULT remain part of the product state model.
8. Personal AMBIENT_HOME and device-control mockup created; same design language with higher information density.

Evaluate senior screens first at realistic viewing distance, not only enlarged on a desktop monitor.
