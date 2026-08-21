# Project Okja — Current Status

Last updated: 2026-08-21 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WORKING — CONTROLLER CORE VERIFIED / WAKE + COMMAND-RECOGNITION NEXT**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`

## Current verdict

The Fold4 local-ASR comparator gate is closed.

- Korean streaming Zipformer: rejected as a primary candidate.
- SenseVoice 2025: rejected as a primary candidate after five same-PCM Fold4 trials.
- Moonshine tiny-ko: remains the incumbent local baseline, but is **not accepted for production physical-device execution**.
- `VoiceSessionController` core is implemented and verified by CI.
- `MainActivity` must not be migrated to the new production voice path until wake and command-recognition/ASR gates pass.

No additional Fold4 input is required for the Moonshine-vs-SenseVoice comparator.

## Architecture implemented

- `AudioEngine` is the sole `AudioRecord` owner.
- Canonical audio: 16 kHz, mono, PCM16, 20 ms frames.
- `PcmRingBuffer` provides pre-roll without microphone handoff.
- Wake/VAD/ASR/diagnostics consume supplied PCM and do not acquire the microphone.
- `PcmFrame` carries monotonic sequence/sample-position metadata.
- `PcmContinuityTracker` detects gaps/out-of-order frames.
- `UtteranceAudioIntegrityGate` latches an utterance untrusted after any PCM discontinuity.
- Physical command authorization must fail closed when PCM integrity is lost.
- Android `SpeechRecognizer` remains compatibility/diagnostic evidence only.

## VoiceSessionController — implemented and verified

The ASR-agnostic controller now owns voice-session lifecycle state outside `MainActivity`.

Implemented invariants:

- one utterance / one decoder path;
- generation tokens reject stale PCM/TTS callbacks;
- bounded recoverable-failure budget;
- explicit `MIC_OFF` / `DEGRADED` states;
- full connected transcript is routed once, so an already-captured command suffix is not discarded;
- TTS speaking state rejects recursive new capture;
- physical device execution requires `UtteranceAudioIntegrityGate.canAuthorizeDeviceCommand()`;
- duplicate/stale finish callbacks cannot execute a device command twice.

Verification:

- CI run `#259` / `32358751275`: **success**;
- deterministic pre-build matrix: success;
- Android JVM tests: success;
- debug APK build: success;
- artifact upload: success.

The controller is implemented as a core component only. It is not yet the production `MainActivity` path.

## Fold4 ASR evidence

Benchmark phrases:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

### Earlier Moonshine vs Zipformer corpus — 10 runs

Moonshine tiny-ko:

- non-empty output: **10/10**;
- semantic suffix: **7/10**;
- conversational `뭐하니`: **4/4**;
- physical device commands: **3/6**;
- mean init: **~625 ms**;
- mean replay/decode: **~160 ms**.

Korean streaming Zipformer:

- non-empty output: **9/10**;
- semantic suffix: **4/10**;
- conversational `뭐하니`: **4/4**;
- physical device commands: **0/6**;
- positive `<EMPTY>` failure: **1/10**;
- mean init: **~1344 ms**;
- mean replay/decode: **~433 ms**.

Decision: Zipformer is historical/fail-fast evidence only.

## Moonshine vs SenseVoice Fold4 gate — five runs

SenseVoice configuration in the APK:

- model: `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`;
- `language = "ko"`;
- inverse text normalization disabled.

### Run 1 — `옥자야 뭐하니`
Saved case: `1787220854150-0`

Moonshine: `옥자야 뭐하니?` — suffix **true**, init 615 ms, decode 135 ms.
SenseVoice: unusable non-Korean/CJK output — suffix **false**, init 1777 ms, decode 316 ms.

### Run 2 — `옥자 TV 켜줘`
Saved case: `1787220869070-1`

Moonshine: `옥자 TV 켜줘.` — suffix **true**, init 609 ms, decode 151 ms.
SenseVoice: unusable mixed Latin/CJK output — suffix **false**, init 2032 ms, decode 339 ms.

### Run 3 — `옥자 에어컨 꺼줘`
Saved case: `1787220883769-2`

Moonshine: unrelated text — suffix **false**, init 618 ms, decode 168 ms.
SenseVoice: unusable CJK output — suffix **false**, init 2033 ms, decode 318 ms.

### Run 4 — `옥자 에어컨 꺼줘`
Saved case: `1787220945621-2`

Moonshine: `독자 에어컨 꺼줘.` — suffix **true**, init 600 ms, decode 161 ms.
SenseVoice: `O渣 ECO 过做`-like mixed output — suffix **false**, init 1999 ms, decode 324 ms.

### Run 5 — `옥자 에어컨 꺼줘`
Saved case: `1787220961785-2`

Moonshine: `먹자 에어컨 꺼줘.` — suffix **true**, init 642 ms, decode 161 ms.
SenseVoice: short unusable CJK output — suffix **false**, init 2050 ms, decode 328 ms.

### Five-run aggregate

Moonshine tiny-ko:

- semantic suffix: **4/5 (80%)**;
- physical device commands: **3/4 (75%)**;
- silent failures: **0/5**;
- mean init: **616.8 ms**;
- mean replay/decode: **155.2 ms**.

SenseVoice 2025:

- semantic suffix: **0/5**;
- physical device commands: **0/4**;
- silent failures: **0/5** — it returned text, but the text was unusable;
- mean init: **1978.2 ms**;
- mean replay/decode: **325.0 ms**.

Decision: **SenseVoice 2025 is removed from the primary candidate path.** No further manual Fold4 repetition is justified for this comparator.

### Combined observed Moonshine evidence

Combining the earlier 10-run corpus with the five SenseVoice-comparison runs:

- semantic suffix: **11/15 (73.3%)**;
- physical device commands: **6/10 (60%)**.

This combined observation is useful engineering evidence, not a production acceptance corpus. The command error modes remain unacceptable for physical actuation.

Known hard failures include:

- `TV 켜줘` -> `TV 꺼줘`;
- `에어컨 꺼줘` -> `에어컨 꺼져`;
- unrelated transcription for a valid AC command.

## Benchmark scoring rules

Transcript fidelity and command preservation remain separate metrics.

Allowed device-token equivalence is deliberately narrow:

- `TV`;
- `티비`;
- `티브이`;
- `텔레비전`.

Punctuation/spacing differences may be ignored for semantic suffix scoring.

Action changes are always failures:

- `켜줘` -> `꺼줘`;
- `꺼줘` -> `꺼져`.

A production physical command must preserve the intended target and action and pass PCM-integrity authorization. Uncertain commands should be rejected rather than guessed.

## Next execution order

### Task E — wake benchmark

First candidate: **Porcupine low-level PCM API**, using only caller-supplied 16 kHz PCM from `AudioEngine`.

Do not use a high-level wake manager that owns microphone capture.

Initial measurements:

- false reject rate;
- false activations/hour;
- keyword-end to detection latency;
- CPU/PSS;
- TV/background-speech robustness;
- TTS self-trigger behavior;
- `옥자` versus longer `옥자야` trigger behavior.

### Task F — command-recognition strategy

Moonshine remains the incumbent full-ASR baseline, not a production authorization source.

Before selecting a final physical-command path, benchmark whether constrained/hybrid recognition can reduce dangerous action inversions. Candidate directions include a command-specialized acoustic classifier or second-pass action verification while general conversation remains on full ASR.

No such hybrid path is selected yet; it must be justified by research and same-PCM/device evidence.

### Task G — end-to-end PCM pipeline

After wake and command-recognition gates are credible:

`AudioEngine -> wake -> pre-roll/live PCM -> ASR/command recognition -> VoiceSessionController -> deterministic router -> TTS`

Keep one microphone owner throughout.

### Task H — production migration

Only after the above gates:

- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove the old Gate -> release -> `SpeechRecognizer` production topology;
- add Android microphone foreground-service lifecycle;
- split diagnostic and release build surfaces;
- run long negative/positive soak tests.

## Current blocker

There is no repository/build blocker.

The open engineering gates are wake reliability and production-safe command recognition. Additional user hardware input is not required until a new benchmark APK is ready.

## Documentation hierarchy

1. `STATUS.md` — current implemented state and next actions.
2. `ARCHITECTURE.md` — target architecture.
3. ADRs — decision rationale.
4. `SECURITY_BACKLOG.md` — deferred security/release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology and candidate status.
6. Historical `AIHUB_*.md` / diagnostic notes — evidence only.
