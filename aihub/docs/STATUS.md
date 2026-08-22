# Project Okja — Current Status

Last updated: 2026-08-22 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WORKING — PHYSICAL ACTION AUTHORITY MOVED OUT OF ASR; CLASSIFIER IMPLEMENTATION NEXT**

Repository: `hansoullee20/ops-console-demo`

Branch: `feat/voice-pipeline-v2`

Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`

Base: `aihub-voice-test`

Latest architecture decision: `architecture/ADR-0004-ACOUSTIC-PHYSICAL-AUTHORITY.md`.

## Current verdict

The production architecture is now fixed around these rules:

1. `AudioEngine` remains the sole `AudioRecord` owner.
2. Physical commands are authorized by a closed-set acoustic path, not generic ASR text.
3. The physical command classes are `{TV_ON, TV_OFF, AC_ON, AC_OFF, OTHER}` with explicit abstention.
4. Moonshine tiny-ko remains the open-language/conversation ASR baseline only.
5. The first new wake-engine benchmark is Porcupine v4.0 low-level caller-owned PCM with `옥자야`.
6. A second-stage wake verifier is optional and will be added only if measured single-engine wake performance requires it.
7. TTS stays half-duplex for v1.
8. `MainActivity` migration remains blocked until wake and physical-command safety gates are credible.

No additional user hardware input is currently required.

## Implemented core

- `AudioEngine`: only microphone owner; 16 kHz mono PCM16, 20 ms frames.
- `PcmRingBuffer`: 3-second history/pre-roll source.
- `PcmFrame`: sequence/sample-position metadata.
- `PcmContinuityTracker`: discontinuity detection.
- `UtteranceAudioIntegrityGate`: missing/discontinuous PCM cannot authorize a physical action.
- `VoiceSessionController`: generation/stale-callback protection, bounded decoder failure handling, TTS recursion blocking, and one-session lifecycle authority.
- Android `SpeechRecognizer`: compatibility/diagnostic path only, not production architecture.

## Physical-command safety work implemented on 2026-08-22

### Commit `c8bc882` — fail physical commands closed behind acoustic authorization

Added:

- `PhysicalCommandClass` with `TV_ON`, `TV_OFF`, `AC_ON`, `AC_OFF`, `OTHER`;
- `PhysicalCommandAuthorizer` caller-owned-PCM contract;
- `PhysicalCommandDecision.Authorized` / `Abstain`;
- fail-closed `RejectingPhysicalCommandAuthorizer` default;
- semantic safety scoring for correct / abstain / wrong-device / wrong-action / false-physical-execution;
- explicit `oppositeActionInversion` signal.

`VoiceSessionController` now feeds the same PCM to the physical authorizer and ASR, but only a typed acoustic `Authorized` decision can call `VoiceDeviceCommandExecutor`.

A `VoiceRouteDecision.DeviceCommand` produced from ASR text is diagnostic only and is blocked if no acoustic authorization exists.

The regression tests include the critical case where ASR text says `TV 꺼줘` but the independent acoustic authorization is `TV_ON`; only the acoustic authorization reaches the executor.

### Commit `7a2b1f3` — physical-command same-PCM benchmark harness

Added:

- `RecordedPhysicalCommandCase`;
- `PhysicalCommandBenchmarkHarness`;
- deterministic caller-owned-PCM replay into a `PhysicalCommandAuthorizer`;
- release-relevant semantic outcomes instead of WER/CER;
- unit cases for correct command, ON/OFF inversion, and false physical execution from `OTHER` audio.

## Fold4 ASR evidence

### Moonshine tiny-ko

Observed combined evidence:

- semantic suffix: 11/15 (73.3%);
- physical device commands: 6/10 (60%);
- typical init: about 0.6 s;
- typical replay/decode: about 0.15–0.16 s.

Observed critical failures include:

- `TV 켜줘 -> TV 꺼줘`;
- `에어컨 꺼줘 -> 에어컨 꺼져`;
- one unrelated transcription for a valid AC command.

Decision: retain for conversation/open-language recognition, never sole physical-action authority.

### SenseVoice 2025

Five Fold4 same-PCM trials:

- semantic suffix: 0/5;
- physical commands: 0/4;
- mean init: 1978.2 ms;
- mean decode: 325.0 ms;
- unusable CJK/mixed-script output.

Decision: rejected primary candidate.

### Korean streaming Zipformer

Earlier Fold4 evidence:

- semantic suffix: 4/10;
- physical commands: 0/6;
- one positive `<EMPTY>` failure;
- mean init: about 1344 ms;
- mean decode: about 433 ms.

Decision: rejected primary candidate.

## Release metrics adopted

Initial qualification gates:

- normal physical-command correctness >= 98%;
- stress-condition correctness >= 95%;
- opposite-action execution = 0 observed in >= 6,000 balanced held-out physical-command trials;
- false physical execution = 0 observed over >= 300 h representative household negatives;
- false wake < 0.1/hour;
- normal-condition missed wake <= 5%;
- action-token clipping = 0 observed in >= 1,000 physical-command utterances;
- no physical execution across PCM/audio-route discontinuity.

Abstention is preferable to wrong physical execution.

## Execution order

### E1 — CURRENT: implement five-class acoustic command classifier

Required output:

```text
TV_ON
TV_OFF
AC_ON
AC_OFF
OTHER
```

The first implementation should target ONNX Runtime CPU. QNN/NPU optimization is deferred until semantic safety and Fold4 latency are measured.

Development pass gate:

- normal-condition correctness >= 98%;
- 0 ON/OFF inversions in >= 3,000 balanced held-out physical-command trials;
- false physical accepts < 0.1% on the development negative set;
- uncertain cases abstain rather than map to the nearest command.

### E2 — Porcupine v4.0 wake benchmark

Integrate Porcupine through its low-level PCM API only; do not use a microphone-owning manager.

Primary phrase: `옥자야`.

Pass gate for the first controlled stage:

- false wake < 0.1/hour over >= 50 h representative negative audio;
- normal missed wake <= 5%;
- same `AudioEngine` PCM source, no second microphone owner.

Continue long-negative accumulation toward the 300+ hour release gate.

### E3 — wake-relative slicing / endpointing calibration

Instrument wake sample position, speech onset, slice boundaries, action-token retention, and trailing silence.

Pass gate:

- command-content retention >= 99%;
- 0 action-token clipping in >= 1,000 physical-command utterances;
- physical endpoint p95 <= 500 ms;
- 0 executable slices spanning a discontinuity.

Do not replace the current VAD unless this measurement shows it is the limiting component.

### E4 — Moonshine conversation-only requalification

Target:

- suffix preservation >= 95% on expanded conversational set;
- conversation semantic success >= 90%;
- decode p95 <= 500 ms;
- speech-end to final result p95 <= 900 ms on Fold4.

If it fails the conversation-only gate, benchmark whisper.cpp multilingual Base/quantized next. This does not change the physical-command architecture.

### E5 — Android/Samsung/TTS hardening

Run screen-off, fold/unfold, Activity recreation, audio-route, Bluetooth, Doze, Samsung sleeping-management, and TTS self-trigger soak tests.

Physical execution must fail closed across every lifecycle/audio discontinuity.

### E6 — production migration

Only after classifier, wake, endpointing, and lifecycle gates pass:

- migrate `MainActivity` to the v2 pipeline;
- add user-started microphone foreground-service lifecycle;
- remove the old `AudioRecord -> release -> SpeechRecognizer` production topology;
- retain diagnostics/replay evidence separately from production authority.

## Current blocker

The next real blocker is training/evaluation data for the five-class acoustic command classifier. The repository now has the runtime authority contract and deterministic safety evaluator, but no qualified classifier/model has yet been connected.

Until that model passes its gate, physical commands remain intentionally fail-closed.

## Documentation hierarchy

1. `STATUS.md` — current implementation and next action.
2. `ARCHITECTURE.md` — target architecture.
3. `architecture/ADR-0004-ACOUSTIC-PHYSICAL-AUTHORITY.md` — latest production decision.
4. earlier ADRs — historical rationale that remains valid where not superseded.
5. `SECURITY_BACKLOG.md` — deferred security/release work.
6. benchmark plans and wake v4 schema/evaluator — evidence methodology.
