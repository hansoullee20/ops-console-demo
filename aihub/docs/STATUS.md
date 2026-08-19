# Project Okja — Current Status

Last updated: 2026-08-19 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WAITING FOR DEVICE BENCHMARK INPUT — CODE NOT BLOCKED**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`
Latest verified engineering head before this documentation update: `a08b57ff96b1227d6a100b09b183375d27b591e5`
Verified CI: GitHub Actions run `#175` / `32243714119` — success
Root-cause checkpoint preserved in history: `8cc9897d6c5898c9ccd5be73599ef91c35f01659`

## Established architecture

- `AudioEngine` is the only production microphone owner.
- Canonical audio is 16 kHz, mono, signed PCM16, 20 ms frames.
- `PcmRingBuffer` provides bounded pre-roll without releasing/reacquiring the microphone.
- Wake/VAD/ASR/diagnostics are PCM consumers and must not create their own `AudioRecord`.
- Deterministic device intent/policy remains ahead of generative AI.
- Android SpeechRecognizer Mode F remains compatibility evidence only, not the production continuous-ASR target.

## Completed engineering work

### 1. PCM integrity contract — core complete

Implemented and tested:

- monotonic `PcmFrame.sequence`;
- absolute `startSampleIndex`;
- `PcmContinuityTracker` for missing/out-of-order frames;
- `UtteranceAudioIntegrityGate`, which latches an utterance untrusted after a gap until a new utterance begins;
- gap/out-of-order/reset/fail-closed unit tests.

Issue #24 stays open only because final enforcement must be wired into the future ASR -> transcript -> physical-device authorization path.

### 2. Same-PCM ASR benchmark harness — core complete

`AsrBenchmarkHarness` now:

- replays the exact same recorded PCM into any `StreamingAsrEngine`;
- preserves canonical frame sequence/sample-position metadata;
- records final transcript, normalized expected-transcript match, command-suffix preservation, first-partial latency, final latency, continuity status, and update count;
- has tests proving different engines receive identical PCM.

Post-task review caught and fixed a latency bug: absolute monotonic timestamps were initially treated as latency. The corrected code subtracts the explicit capture-start monotonic timestamp and has a regression test with a non-zero clock origin.

CI run #164 passed after that correction.

### 3. sherpa-onnx Korean streaming adapter — code complete

Implemented:

- pinned Android runtime dependency `com.github.k2-fsa:sherpa-onnx:v1.13.4`;
- JitPack repository configuration;
- `SherpaStreamingAsrEngine` implementing the existing `StreamingAsrEngine` contract;
- official Korean streaming Zipformer model type `14` (`sherpa-onnx-streaming-zipformer-korean-2024-06-16`);
- PCM16 -> normalized float conversion;
- pre-roll + live PCM ingestion without any `AudioRecord` ownership;
- partial/final `AsrUpdate` timestamps using Android monotonic time;
- model provisioning script `aihub/tools/fetch_sherpa_korean_model.sh`;
- large model assets excluded from Git with `aihub/.gitignore`.

CI run #175 passed deterministic checks, Android JVM tests, debug APK build, and artifact upload on this integration.

## Remaining execution plan

### Task 4 — Real same-PCM Fold4 benchmark — NEXT

Required inputs not yet present in the repository:

- a recorded 16 kHz PCM benchmark corpus from the target Fold4 / target speaking conditions;
- the provisioned Korean sherpa model files on the device build.

Minimum connected-utterance set should include repeated trials of:

- `옥자야 뭐하니`
- `옥자 TV 켜줘`
- `옥자 에어컨 꺼줘`
- negatives / TV-background / quieter speech samples.

Compare sherpa streaming Zipformer against the Android SpeechRecognizer compatibility path on identical PCM where technically possible.

Measure:

- command suffix preservation;
- transcript accuracy and later WER/CER;
- first-partial/final latency;
- CPU;
- peak PSS;
- thermal/battery behavior;
- PCM discontinuity count;
- system recognition cue count;
- duplicate execution count.

Initial production-path acceptance target remains:

- command suffix preserved >= 98/100 connected wake+command trials;
- no microphone reacquisition between wake and command capture;
- no Android SpeechRecognizer system cue on the final local path;
- duplicate physical command execution = 0.

### Task 5 — VoiceSessionController

After the first PCM-fed local ASR passes the device gate:

- move voice lifecycle authority out of `MainActivity`;
- enforce one microphone owner and one ASR decoding path per utterance;
- reject stale callbacks;
- bound retries;
- make MIC_OFF and TTS transitions deterministic;
- require `UtteranceAudioIntegrityGate.canAuthorizeDeviceCommand()` before physical execution.

### Task 6 — Wake engine benchmark

Compare PCM-fed wake candidates without changing microphone ownership:

- Porcupine low-level baseline;
- sherpa-onnx KWS.

### Task 7 — Production migration

After ASR/wake acceptance:

- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove the old Gate -> release -> SpeechRecognizer production path;
- separate diagnostic and release build surfaces.

### Task 8 — Later release gates

- dedicated `project-okja` repository extraction (#22);
- deferred security release gates (#21);
- archive legacy `AIHUB_*.md` after canonical docs remain stable (#25).

## Current blocker / required external input

No architecture or compile blocker remains.

The next meaningful step is a **real Fold4 benchmark**, which cannot be truthfully completed from repository code alone because the target-device recorded corpus and provisioned model runtime on that device are not currently available here. Do not claim device performance until those measurements exist.

## Documentation hierarchy

1. `STATUS.md` — current state and next actions.
2. `ARCHITECTURE.md` — intended production architecture.
3. `architecture/ADR-*.md` — decision rationale.
4. `SECURITY_BACKLOG.md` — known security work and release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology.
6. Historical `AIHUB_*.md` and diagnostic notes — evidence/context, not current source of truth.
