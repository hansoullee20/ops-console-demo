# Project Okja — Current Status

Last updated: 2026-08-19 (Asia/Seoul)

This file is the authoritative answer to: **Where is Project Okja right now, what is done, what is blocked, and what happens next?**

## Project state

**STATE: READY TO CONTINUE — NOT BLOCKED**

The project is not waiting on an unresolved architecture decision. The current voice direction is established and the next work is implementation/benchmarking.

## Active development

- Repository: `hansoullee20/ops-console-demo`
- Active branch: `feat/voice-pipeline-v2`
- Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
- Base branch for the PR: `aihub-voice-test`
- Current verified head: `ff4f08a2aae40e1ead811a512934ab7193d2d9cd`
- Current verified CI: GitHub Actions run `#150` / run ID `32242653598` — success
- Diagnostic/root-cause checkpoint preserved in history: `8cc9897d6c5898c9ccd5be73599ef91c35f01659`

## What works / what is established

### Voice root cause

Fold4 diagnostics established the important architecture failure in the old path:

```text
QuietWakeGate / AudioRecord
        -> release AudioRecord
        -> Android SpeechRecognizer
```

This handoff can lose the beginning of a connected utterance such as `옥자야 뭐하니`. A separate issue in the old `MainActivity` also discards the already-recognized command suffix and starts another SpeechRecognizer session.

The old cooldown/retrigger tuning is therefore not treated as a root fix.

### New audio-core architecture

PR #20 establishes:

- `AudioEngine` as the only production microphone owner.
- Canonical PCM: 16 kHz, mono, signed PCM16, 20 ms frames.
- `PcmRingBuffer` with configurable capacity; initial capacity is 3000 ms.
- Configurable pre-roll; initial default is 1500 ms.
- `PcmAudioSource` consumer contract.
- Microphone-free `WakeDetector` contract.
- Microphone-free `StreamingAsrEngine` contract.
- Unit tests for wrap-around and pre-roll behavior.

Production rule: wake, VAD, ASR, and diagnostics consume PCM. They do not create a competing `AudioRecord`.

### PCM continuity integrity

Commit `ff4f08a` adds the first SEC-006 audio-integrity layer:

- every `PcmFrame` now carries a monotonic capture `sequence`;
- every frame carries an absolute `startSampleIndex`;
- `PcmContinuityTracker` detects gaps and out-of-order frames;
- unit tests cover continuous input, skipped-frame gaps, out-of-order input, and reset epochs;
- CI run #150 passed JVM tests, Android build, and the existing deterministic pre-build matrix.

Important remaining integration rule: when the new ASR/router path is connected, any utterance with a detected PCM discontinuity must fail closed for physical-device execution until a clean utterance begins. Issue #24 remains open until that enforcement is wired into the real transcript/device path.

### Intent / device boundary

Existing deterministic handling remains valuable and should be preserved:

- known device intents are handled before generative AI;
- explicit negation patterns reject commands such as `켜지 마`;
- confirmation is scoped to device/profile/session/correlation;
- device-command contracts validate target/action/parameters, expiry, and idempotency;
- physical adapters are not yet considered production-ready.

### Backend

Two prototype bridge implementations exist under `phone/`:

- `aihub_bridge.py` — Claude Agent SDK path;
- `aihub_bridge_codex.py` — Codex CLI path.

For the current prototype, these remain development backends. Fresh Codex CLI execution is not the intended long-term household production backend.

## What is intentionally NOT finished

- No final wake-word engine is selected.
- No final Korean ASR engine is selected.
- `MainActivity` has not yet been migrated to the new `AudioEngine` path.
- Android SpeechRecognizer Mode F is compatibility evidence only, not the target architecture.
- PCM discontinuity is detectable but is not yet wired into ASR/device-command fail-closed routing because the new ASR/router path does not exist yet.
- No production barge-in implementation yet.
- No QNN/NPU optimization yet.
- No real security-sensitive home-device integration yet.
- Dedicated `project-okja` repository extraction has not yet been performed.

## Itemized execution plan

### Task 1 — PCM integrity contract

**Status: implementation complete; integration enforcement pending.**

- Add sequence/sample-position metadata to `PcmFrame`. — DONE
- Add consumer continuity detection. — DONE
- Add unit tests for gap/out-of-order detection. — DONE
- Verify CI. — DONE
- Fail closed on discontinuous utterances in the eventual ASR/device router. — PENDING integration

Tracked by issue #24.

### Task 2 — Same-PCM benchmark harness

**Status: NEXT ACTIVE ENGINEERING TASK.**

Create a harness that feeds identical recorded PCM to candidate ASR engines without changing microphone ownership.

Primary comparisons:

- sherpa-onnx Korean streaming Zipformer;
- sherpa Moonshine tiny-ko where appropriate;
- Android SpeechRecognizer Mode F compatibility path.

Measure transcript quality, connected wake+command preservation, first-partial latency, final latency, CPU, memory, and device stability.

Tracked by issue #23.

### Task 3 — Fold4 local-ASR spike

Integrate the first sherpa-onnx Korean streaming model behind `StreamingAsrEngine` and validate on the Galaxy Z Fold4.

Initial acceptance target:

- connected utterance command suffix preserved >= 98/100;
- no microphone reacquisition between wake and command capture;
- no Android SpeechRecognizer system cue on the final local path;
- no duplicate command execution.

### Task 4 — VoiceSessionController

Move voice lifecycle authority out of `MainActivity` into an explicit state machine after the first PCM-fed ASR passes the device gate.

Required properties include:

- one microphone owner;
- no unnecessary second recognizer when command audio/transcript already exists;
- bounded retries;
- stale callback rejection;
- deterministic MIC_OFF and TTS transitions;
- reject device execution from an utterance marked PCM-discontinuous.

### Task 5 — Wake engine benchmark

Attach PCM-fed wake candidates without changing microphone ownership:

- Porcupine low-level baseline;
- sherpa-onnx KWS candidate.

Measure false reject, false activations/hour, TV/background robustness, quiet/elderly speech, CPU and battery.

### Task 6 — Production migration

Only after the local ASR/wake gates are proven:

- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove the old Gate -> release -> SpeechRecognizer production path;
- separate diagnostic and release build surfaces.

### Task 7 — Later release gates

- dedicated `project-okja` repository extraction (#22);
- deferred security release gates (#21);
- archive legacy `AIHUB_*.md` after canonical docs remain stable (#25).

## Current blocker

**None.**

If work is not actively being performed, the correct status is `WAITING FOR NEXT TURN`, not `WORKING`.

## Security posture

Current prototype security findings are tracked in [`SECURITY_BACKLOG.md`](SECURITY_BACKLOG.md).

Security hardening is deliberately deferred enough to avoid blocking the family prototype, but the following become release gates **before** broader deployment or security-sensitive devices:

- authenticated local IPC / peer identity;
- actuator-boundary authorization;
- production AI backend without broad coding-agent machine privileges;
- trusted command risk tiers;
- production/diagnostic build separation.

## Documentation hierarchy

1. `STATUS.md` — current state and next actions.
2. `ARCHITECTURE.md` — intended production architecture.
3. `architecture/ADR-*.md` — why major decisions were made.
4. `SECURITY_BACKLOG.md` — known security work and release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology.
6. Historical `AIHUB_*.md`, wake-word evidence, and diagnostic notes — preserved context, not current source of truth.
