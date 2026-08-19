# Project Okja — Current Status

Last updated: 2026-08-19 (Asia/Seoul)

This file is the authoritative answer to: **Where is Project Okja right now, what is done, what is blocked, and what happens next?**

## Project state

**STATE: READY TO CONTINUE — NOT BLOCKED**

The current voice direction is established. Work has advanced through the PCM integrity layer and the first same-PCM ASR replay harness. The next step is a real sherpa-onnx Korean streaming adapter and Fold4 benchmark.

## Active development

- Repository: `hansoullee20/ops-console-demo`
- Active branch: `feat/voice-pipeline-v2`
- Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
- Base branch for the PR: `aihub-voice-test`
- Current verified head: `c34f928cb25fca0e84256edfa61f16dec711f238`
- Current verified CI: GitHub Actions run `#164` / run ID `32243222671` — success
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

The current branch now includes:

- monotonic `PcmFrame.sequence`;
- absolute `startSampleIndex` / end sample position;
- `PcmContinuityTracker` for missing/out-of-order PCM detection;
- `UtteranceAudioIntegrityGate`, which latches an utterance untrusted after any detected gap until a new utterance begins;
- tests covering continuous input, skipped-frame gaps, out-of-order input, reset epochs, and fail-closed utterance trust.

Issue #24 remains open until this gate is wired into the real ASR -> transcript -> physical-device authorization path. The core integrity mechanism itself is implemented and tested.

### Same-PCM ASR benchmark foundation

`AsrBenchmarkHarness` now exists and replays the exact same recorded 16 kHz PCM into any `StreamingAsrEngine` without microphone ownership.

It records:

- final transcript;
- exact normalized expected-transcript match where supplied;
- command-suffix preservation;
- first-partial latency;
- final latency;
- replay continuity status;
- ASR update count.

The harness includes tests proving that different engines receive identical PCM and canonical frame metadata.

Post-implementation review found and fixed a real timing bug in the first version: absolute monotonic `producedAtElapsedRealtimeNs` values were initially treated as latency values. The corrected implementation subtracts an explicit capture-start monotonic timestamp, with a regression test using a non-zero clock origin.

CI run #164 passed deterministic checks, Android JVM tests, APK build, and artifact upload on the reviewed harness.

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
- No real sherpa-onnx `StreamingAsrEngine` implementation is integrated yet.
- The benchmark harness does not yet collect real-device CPU/PSS/thermal/battery data.
- WER/CER scoring is not yet added to the real-engine/device benchmark layer.
- `MainActivity` has not yet been migrated to the new `AudioEngine` path.
- Android SpeechRecognizer Mode F is compatibility evidence only, not the target architecture.
- PCM discontinuity fail-closed logic is not yet connected to the real physical-command authorization path.
- No production barge-in implementation yet.
- No QNN/NPU optimization yet.
- No real security-sensitive home-device integration yet.
- Dedicated `project-okja` repository extraction has not yet been performed.

## Itemized execution plan

### Task 1 — PCM integrity contract

**Status: CORE COMPLETE; ROUTER INTEGRATION PENDING.**

- Add sequence/sample-position metadata to `PcmFrame`. — DONE
- Add consumer continuity detection. — DONE
- Add utterance-level fail-closed trust latch. — DONE
- Add unit tests for gap/out-of-order/fail-closed behavior. — DONE
- Verify CI. — DONE
- Enforce gate in the eventual ASR/device authorization path. — PENDING integration

Tracked by issue #24.

### Task 2 — Same-PCM benchmark harness

**Status: CORE HARNESS COMPLETE AND REVIEWED.**

- Replay identical PCM into multiple `StreamingAsrEngine` implementations. — DONE
- Preserve canonical 20 ms frame metadata. — DONE
- Capture transcript/suffix/latency fields. — DONE
- Verify two engines receive identical PCM. — DONE
- Review latency math against real monotonic timestamps. — DONE / bug fixed
- Add real engine adapters and device metrics. — NEXT

Tracked by issue #23.

### Task 3 — sherpa-onnx Korean streaming adapter

**Status: NEXT ACTIVE ENGINEERING TASK.**

Integrate a pinned sherpa-onnx Android runtime behind `StreamingAsrEngine` using the Korean streaming Zipformer model as the first real candidate.

Requirements:

- consume PCM only; never create `AudioRecord`;
- normalize PCM16 to float input expected by sherpa;
- accept pre-roll followed by live frames;
- expose partial/final `AsrUpdate` timestamps on the same monotonic clock;
- pin runtime/model version and record model hashes/provenance;
- keep model files out of source control unless deliberately vendored.

### Task 4 — Fold4 same-PCM benchmark

Run the same corpus against the real sherpa engine and the Android SpeechRecognizer compatibility path.

Initial acceptance target:

- connected utterance command suffix preserved >= 98/100;
- no microphone reacquisition between wake and command capture;
- no Android SpeechRecognizer system cue on the final local path;
- no duplicate command execution.

Add real-device metrics:

- exact transcript / command accuracy;
- WER/CER;
- first-partial/final latency;
- CPU;
- peak PSS;
- thermal/battery behavior.

### Task 5 — VoiceSessionController

Move voice lifecycle authority out of `MainActivity` after the first PCM-fed ASR passes the device gate.

Required properties include:

- one microphone owner;
- no unnecessary second recognizer when command audio/transcript already exists;
- bounded retries;
- stale callback rejection;
- deterministic MIC_OFF and TTS transitions;
- reject physical-device execution from an utterance marked PCM-discontinuous.

### Task 6 — Wake engine benchmark

Attach PCM-fed wake candidates without changing microphone ownership:

- Porcupine low-level baseline;
- sherpa-onnx KWS candidate.

Measure false reject, false activations/hour, TV/background robustness, quiet/elderly speech, CPU and battery.

### Task 7 — Production migration

Only after the local ASR/wake gates are proven:

- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove the old Gate -> release -> SpeechRecognizer production path;
- separate diagnostic and release build surfaces.

### Task 8 — Later release gates

- dedicated `project-okja` repository extraction (#22);
- deferred security release gates (#21);
- archive legacy `AIHUB_*.md` after canonical docs remain stable (#25).

## Current blocker

**None.**

The next likely external dependency is obtaining/deploying the selected sherpa Korean model onto the Fold4 for runtime benchmarking. That is not yet a blocker for code integration.

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
