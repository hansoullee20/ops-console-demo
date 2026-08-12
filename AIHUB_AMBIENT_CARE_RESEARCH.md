# AI Hub / Okja — Ambient Care & Presence Research

Date: 2026-08-12
Status: research translated into implementable architecture

## Goal

Use proven smart-home and on-device sensing patterns from large platforms and recent elder-care research, while keeping Okja privacy-first, inexpensive, and implementable on Android-class hardware.

## Large-platform patterns worth copying

### 1. Sensor fusion for presence, not one signal
Google Home presence sensing combines phone geofence/Wi-Fi with activity from smart-home devices. Google Home APIs expose OccupancySensing and event streams. Amazon exposes MotionSensor, ContactSensor and SmartVision ObjectDetection events.

**Okja adaptation:** represent presence as a confidence score fed by several weak signals:
- camera person detected / direction of travel;
- door/contact event if available;
- phone geofence/Wi-Fi presence when companion app exists;
- local voice activity / recent Okja interaction;
- optional Matter occupancy sensor.

Do not infer HOME/AWAY from a single camera frame.

### 2. Event-first architecture
Amazon SmartVision reports timestamped object events immediately, with unique identifiers and optional images, instead of treating the entire video stream as the product data model.

**Okja adaptation:** retain structured events by default, not continuous video:
`PERSON_ENTERED`, `PERSON_EXITED`, `PRESENCE_CHANGED`, `FALL_SUSPECTED`, `NO_ACTIVITY_ALERT`, etc. Optional short evidence clips can be retained only when explicitly enabled.

### 3. Explicit state-change thresholds and hold times
Google OccupancySensing exposes occupied/unoccupied delays and event thresholds. This prevents noisy sensors from flipping state immediately.

**Okja adaptation:** use hysteresis:
- require N consistent detections before ENTRY/EXIT;
- use a hold period before declaring AWAY;
- keep `UNKNOWN` as a real state rather than forcing HOME/AWAY.

### 4. Low-power cascades
Apple's Raise to Speak work uses multiple lightweight on-device detectors and a policy model rather than running the expensive path continuously.

**Okja adaptation:** sensing cascade:
1. cheap motion/person-presence trigger;
2. lightweight local person/pose model only when activity exists;
3. heavier analysis only on suspicious sequences;
4. optional cloud reasoning only after explicit event generation.

This should reduce CPU, thermals and privacy exposure.

### 5. Multimodal fall detection and confirmation
Recent systematic reviews find deep-learning methods strong in fall detection, but real-world validation is still limited and false alarms remain a major problem. Sensor-fusion literature consistently supports combining modalities instead of trusting one detector.

**Okja adaptation:** never map one pose classifier directly to emergency calling. Use:
- rapid vertical displacement / pose change;
- person remains low/still;
- optional impact/acoustic cue;
- absence of recovery motion;
- voice confirmation: “괜찮으세요?”;
- only then escalation according to configured policy.

## Proposed Okja presence state machine

States:
- `UNKNOWN`
- `HOME_ACTIVE`
- `HOME_QUIET`
- `AWAY_PENDING`
- `AWAY`
- `RETURN_PENDING`

Signals have independent timestamps and confidence values. Example transition:

`HOME_ACTIVE` → exit-direction person event + door event → `AWAY_PENDING`

If phone/Wi-Fi is also absent for a hold period → `AWAY`.

If evidence conflicts, return to `UNKNOWN` rather than issue a false family alert.

## Family notification model

Two directions are needed.

### Family → senior
A family member can tap an action such as:
- “집에 가는 중이에요”
- “곧 도착해요”
- custom short message

The senior Okja receives a calm, large notification and may optionally read it aloud.

Example:
`큰아들이 집으로 오고 있어요. 약 25분 뒤 도착 예정이에요.`

### Senior → family
Configured family members may receive event notifications such as:
- `할머니가 오전 9:12에 외출하셨어요.`
- `할머니가 오전 11:03에 귀가하셨어요.`
- `평소보다 오랫동안 활동이 감지되지 않았어요. 확인해 보세요.`

These must be opt-in and configurable by event type. Presence uncertainty must be displayed when confidence is low.

## Care escalation levels

### Level 0 — normal events
Home/away, device state, wellness record.

### Level 1 — informational anomaly
Long quiet period outside usual baseline. No emergency language. Family may receive a low-priority notification.

### Level 2 — safety check
Suspicious fall or distress signal. Okja asks the senior whether they are okay and opens the safety UI.

### Level 3 — configured emergency escalation
Explicit user request or confirmed high-confidence emergency. Notify configured family group and follow emergency-call policy.

## Privacy defaults

- Camera care features opt-in.
- Prefer on-device inference.
- Store event metadata instead of full video.
- Short evidence window only for safety debugging/verification if enabled.
- User/family controls for which presence events are shared.
- Clear camera/microphone indicators.
- Allow history deletion.

## Implementation phases

### Phase P1 — no camera ML required
- family → senior “집에 가는 중” event;
- senior → family manual/phone-assisted home-away updates;
- notification preferences and event schema;
- UI cards.

### Phase P2 — local person presence
- Android camera frame sampler;
- lightweight person detector;
- temporal tracker;
- entry/exit direction estimation;
- local event generation only.

### Phase P3 — sensor fusion
- phone geofence/Wi-Fi;
- Matter occupancy/contact sensors where available;
- confidence fusion + hysteresis state machine;
- baseline activity model.

### Phase P4 — fall-suspicion pipeline
- local pose estimation;
- temporal motion features;
- confirmation dialogue;
- staged family/emergency escalation;
- extensive real-world false-positive testing before unattended action.

## References reviewed

- Google Home presence sensing / Home & Away: combines phone location with device activity.
- Google Home OccupancySensing APIs / Matter occupancy event support.
- Amazon Alexa MotionSensor / ContactSensor / SmartVision ObjectDetection event model.
- Apple ML Research “Raise to Speak”: multi-detector low-power cascade and policy fusion.
- 2025 systematic review/meta-analysis of smart-home fall technology in older adults.
- 2025 systematic review of ambient-assisted-living fall detection performance.
- Fall-detection literature emphasizing sensor fusion and false-alarm reduction.

## Design decision

For Okja, the reusable architectural primitive is **timestamped local events + confidence + policy**, not continuous surveillance and not a single monolithic AI model.
