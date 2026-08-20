# Project Okja — Current Status

Last updated: 2026-08-20 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WORKING — SENSEVOICE GATE CLOSED / VOICE SESSION CORE NEXT**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`

## Current verdict

The Fold4 local-ASR comparator gate is now resolved.

- Korean streaming Zipformer: rejected as a primary candidate.
- SenseVoice 2025: rejected as a primary candidate after the three-phrase Fold4 gate.
- Moonshine tiny-ko: remains the best observed local candidate, but **is not production-ready for physical device commands**.

Do not merge or migrate `MainActivity` to a production local-ASR path yet. Continue the ASR-agnostic voice-session core while the final production ASR accuracy gate remains open.

## Architecture already implemented

- `AudioEngine` is the sole `AudioRecord` owner.
- Canonical audio: 16 kHz, mono, PCM16, 20 ms frames.
- Wake/VAD/ASR/diagnostics consume shared PCM and must not acquire the microphone independently.
- `PcmRingBuffer` provides pre-roll without microphone handoff.
- `PcmFrame` carries monotonic sequence/sample-position metadata.
- `PcmContinuityTracker` detects gaps/out-of-order frames.
- `UtteranceAudioIntegrityGate` latches an utterance untrusted after any PCM discontinuity and must gate physical command authorization.
- Deterministic device routing stays ahead of generative AI.
- Android `SpeechRecognizer` remains compatibility/diagnostic evidence, not the continuous production path.

## Fold4 baseline corpus

The benchmark corpus contains exactly three phrases:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

### Earlier Moonshine vs Zipformer evidence

Across 10 unique saved Fold4 runs visible in the supplied screenshots:

Moonshine tiny-ko:
- non-empty output: **10/10**
- semantic suffix preserved overall: **7/10 (70%)**
- conversational `뭐하니`: **4/4**
- physical device commands: **3/6 (50%)**
- mean init: **~625 ms**
- mean replay/decode: **~160 ms**

Korean streaming Zipformer:
- non-empty output: **9/10**
- positive `<EMPTY>` failure: **1/10**
- semantic suffix preserved overall: **4/10 (40%)**
- conversational `뭐하니`: **4/4**
- physical device commands: **0/6 (0%)**
- mean init: **~1344 ms**
- mean replay/decode: **~433 ms**

Decision: Zipformer is historical/fail-fast comparison only.

## Fold4 Moonshine vs SenseVoice gate — completed

Verified APK:
- model workflow run: `#15` / `32328314309` — success
- normal verification run: `#249` / `32328314338` — success
- artifact ID: `9392185590`
- APK SHA-256: `9b293f486db2a7068286cba0bd9261b038f35c4b33725805c4803f7ca2bf1e49`
- SenseVoice config: explicit `language = ko`, ITN disabled

Three same-PCM Fold4 trials supplied by the user:

### 1. `옥자야 뭐하니`
Saved case: `1787220854150-0`

Moonshine:
- transcript: `옥자야 뭐하니?`
- semantic suffix: **true**
- silent failure: false
- init: **615 ms**
- replay/decode: **135 ms**

SenseVoice 2025:
- returned non-Korean / CJK-garbled text
- semantic suffix: **false**
- silent failure: false
- init: **1777 ms**
- replay/decode: **316 ms**

### 2. `옥자 TV 켜줘`
Saved case: `1787220869070-1`

Moonshine:
- transcript: `옥자 TV 켜줘.`
- semantic suffix: **true**
- silent failure: false
- init: **609 ms**
- replay/decode: **151 ms**

SenseVoice 2025:
- returned mixed Latin/CJK garbage text
- semantic suffix: **false**
- silent failure: false
- init: **2032 ms**
- replay/decode: **339 ms**

### 3. `옥자 에어컨 꺼줘`
Saved case: `1787220883769-2`

Moonshine:
- transcript: `복자예요. 큰 포즈.`
- semantic suffix: **false**
- silent failure: false
- init: **618 ms**
- replay/decode: **168 ms**

SenseVoice 2025:
- returned short CJK garbage text
- semantic suffix: **false**
- silent failure: false
- init: **2033 ms**
- replay/decode: **318 ms**

### Three-phrase aggregate

Moonshine:
- semantic suffix: **2/3**
- physical device commands: **1/2**
- mean init: **~614 ms**
- mean replay/decode: **~151 ms**

SenseVoice 2025:
- semantic suffix: **0/3**
- physical device commands: **0/2**
- silent failures: **0/3** (it returned text, but the text was unusable)
- mean init: **~1947 ms**
- mean replay/decode: **~324 ms**

Decision: **SenseVoice 2025 is removed from the primary candidate path.** No additional user repetition is justified for this comparator.

The upstream sherpa-onnx API accepts SenseVoice language `ko`, and the branch explicitly sets it. Therefore this gate is treated as a device-observed integration/model failure rather than a missing language-hint configuration. Deeper SenseVoice diagnosis is not on the critical path unless it becomes useful later.

## Benchmark metric rules

Transcript fidelity and command preservation are separate metrics.

Allowed device-token equivalence is intentionally narrow:
- `TV`
- `티비`
- `티브이`
- `텔레비전`

Action changes are never normalized away:
- `켜줘` -> `꺼줘` = failure
- `꺼줘` -> `꺼져` = failure

Physical device execution requires intended target + action preservation and clean PCM integrity.

## Next execution order

### Task D — bounded `VoiceSessionController`

Implement the ASR-agnostic core without migrating `MainActivity` yet.

Conceptual states:
`IDLE -> CAPTURING -> ROUTING -> SPEAKING -> FOLLOW_UP/IDLE`

Any state may transition to `MIC_OFF` / `DEGRADED`.

Required invariants:
- one microphone owner;
- one decoder path per utterance;
- generation/stale-callback protection;
- bounded retries;
- deterministic MIC_OFF/TTS transitions;
- preserve command suffix already present in the wake utterance;
- require `UtteranceAudioIntegrityGate.canAuthorizeDeviceCommand()` before physical execution;
- TTS must not recursively trigger wake/command execution.

### ASR accuracy gate — still open

Moonshine remains the leading observed candidate but is not accepted for production command execution. A later comparator/tuning step may be needed, but it should not block the ASR-agnostic controller core.

### Wake benchmark

1. Porcupine low-level PCM Korean/custom wake baseline.
2. sherpa KWS only if Korean model/tokenization support is evidenced.

### Production migration

Only after ASR/wake acceptance:
- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove old Gate -> release -> `SpeechRecognizer` production topology;
- add current-Android microphone foreground-service lifecycle;
- split diagnostic and release surfaces.

Later release gates remain separate: dedicated repo extraction (#22), deferred security work (#21), and legacy-doc archive (#25).

## Documentation hierarchy

1. `STATUS.md`
2. `ARCHITECTURE.md`
3. ADRs
4. `SECURITY_BACKLOG.md`
5. `VOICE_ENGINE_BENCHMARK_PLAN.md`
6. legacy AIHUB/diagnostic notes
