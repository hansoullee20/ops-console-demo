# Project Okja — Current Status

Last updated: 2026-08-21 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WORKING — STAGED WAKE / HYBRID COMMAND PLAN ACCEPTED, ANDROID WAKE EVIDENCE BRIDGE UNDER VERIFICATION**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`

## Current verdict

The Fold4 full-ASR comparator gate is closed.

- Korean streaming Zipformer: rejected as a primary candidate.
- SenseVoice 2025: rejected as a primary candidate after five same-PCM Fold4 trials.
- Moonshine tiny-ko: remains the incumbent local full-ASR baseline, but is **not accepted for production physical-device execution**.
- `VoiceSessionController` core is implemented and CI-verified.
- Deep-research findings are adopted as the implementation direction: staged wake detection, long-negative wake measurement, and hybrid/constrained authorization for physical commands.
- Existing v4 wake benchmark infrastructure is the canonical long-duration evidence system; new Android code bridges caller-owned PCM into that contract rather than creating a competing benchmark format.
- `MainActivity` must not be migrated until wake and physical-command safety gates are credible.

No additional Fold4 input is currently required from the user.

## Implemented architecture

- `AudioEngine` is the sole `AudioRecord` owner.
- Canonical audio: 16 kHz, mono, PCM16, 20 ms frames.
- `PcmRingBuffer` provides pre-roll without microphone handoff.
- Wake/VAD/ASR/diagnostics consume caller-owned PCM.
- `PcmFrame` carries monotonic sequence/sample-position metadata.
- `PcmContinuityTracker` detects gaps/out-of-order frames.
- `UtteranceAudioIntegrityGate` fails physical command authorization closed after any PCM discontinuity.
- Android `SpeechRecognizer` is compatibility/diagnostic evidence only.

## VoiceSessionController — implemented and verified

Implemented invariants:

- one utterance / one decoder path;
- generation tokens reject stale PCM/TTS callbacks;
- bounded recoverable-failure budget;
- explicit `MIC_OFF` / `DEGRADED` states;
- a command suffix already captured with the wake phrase is routed once instead of being discarded;
- TTS speaking state rejects recursive new capture;
- physical execution requires `UtteranceAudioIntegrityGate.canAuthorizeDeviceCommand()`;
- duplicate/stale finish callbacks cannot execute twice.

Verification:

- CI run `#259` / `32358751275`: **success**;
- deterministic pre-build matrix: success;
- Android JVM tests: success;
- debug APK build: success;
- artifact upload: success.

The controller is not yet wired as the production `MainActivity` lifecycle owner.

## Fold4 ASR evidence

Core benchmark phrases:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

### Moonshine tiny-ko

Earlier 10-run corpus:

- semantic suffix: **7/10**;
- conversational `뭐하니`: **4/4**;
- physical device commands: **3/6**;
- mean init: **~625 ms**;
- mean replay/decode: **~160 ms**.

Five later same-PCM runs:

- semantic suffix: **4/5**;
- physical device commands: **3/4**;
- mean init: **616.8 ms**;
- mean replay/decode: **155.2 ms**.

Combined observed evidence:

- semantic suffix: **11/15 (73.3%)**;
- physical device commands: **6/10 (60%)**.

Known hard failures include:

- `TV 켜줘` -> `TV 꺼줘`;
- `에어컨 꺼줘` -> `에어컨 꺼져`;
- unrelated transcription for a valid AC command.

Decision: Moonshine remains the full-ASR baseline for comparison/conversation, not physical actuator authority.

### SenseVoice 2025

Configuration:

- model: `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`;
- `language = "ko"`;
- inverse text normalization disabled.

Five Fold4 same-PCM trials:

- semantic suffix: **0/5**;
- physical commands: **0/4**;
- mean init: **1978.2 ms**;
- mean replay/decode: **325.0 ms**;
- non-empty but unusable CJK/mixed-script text.

Decision: rejected primary candidate; stop manual collection.

### Korean streaming Zipformer

Earlier Fold4 evidence:

- semantic suffix: **4/10**;
- physical commands: **0/6**;
- positive `<EMPTY>` failure: **1/10**;
- mean init: **~1344 ms**;
- mean replay/decode: **~433 ms**.

Decision: historical/fail-fast evidence only.

## Research-backed architecture decisions adopted on 2026-08-21

See `architecture/ADR-0003-STAGED-WAKE-HYBRID-COMMAND.md`.

### Wake

Target topology:

```text
AudioEngine PCM
  -> Stage A high-recall KWS
  -> Stage B high-precision Okja phrase verifier
  -> optional speaker policy
  -> directed-speech / command gate
  -> recognition
```

Candidate order:

1. **openWakeWord** — first open/custom Stage-A implementation path;
2. **Porcupine low-level PCM** — independent Korean/Android commercial benchmark control, not the default final licensing choice;
3. **sherpa-onnx KWS** — longer-term open runtime candidate after an Okja/Korean model path is evidenced.

Primary benchmark trigger: `옥자야`.
Short alias/control: `옥자`, with stronger Stage-B scrutiny.

### Physical commands

Unrestricted full-ASR text is not a sufficient production authorization source.

Target policy:

```text
full ASR
  + command-specialized acoustic/verifier evidence
  + deterministic target/action validation
  + clean PCM integrity
  -> execute only when evidence is consistent
```

Any target/action disagreement becomes abstention / ask-again.

General conversation still uses full ASR.

### Wake measurement progression

```text
10 min developer replay
  -> 1 h controlled room
  -> 24 h household smoke
  -> 100 h multi-condition negative
  -> 300+ h release-gate negative
  -> multi-household pilot
```

Wake reports must include recall/FRR, false activations/hour, P50/P95 latency, TV/background false activations, self-TTS false activations, CPU/PSS, and later battery/thermal metrics.

Zero false activations over about 300 negative hours corresponds to an approximate 95% Poisson upper bound near 0.01 false activations/hour (`~3/T`).

### TTS and Android lifecycle

- first production behavior stays half-duplex: `VoiceSessionController` blocks wake/capture during TTS;
- full-duplex/AEC is deferred until measured need;
- the eventual microphone foreground service must be launched from a visible/user-authorized Android flow rather than assuming arbitrary background microphone-service start is allowed.

## Wake benchmark infrastructure — canonical vs Android bridge

The branch already contains a mature Python-side v4 benchmark system:

- `wakeword/v4_benchmark_schema.json` — canonical truth/detection JSON contract;
- `wakeword/v4_benchmark_contract.py` — contract validation;
- `wakeword/v4_eval.py` — one-to-one matching, recall/FRR, FPPH, confidence intervals, P50/P95, condition breakdowns, threshold sweep;
- `wakeword/v4_replay.py` — deterministic replay infrastructure;
- `wakeword/v4_ring_buffer_logger.py` — privacy-first candidate/manual-miss reference capture;
- `wakeword/AIHUB_V4_HOUSEHOLD_BENCHMARK_SPEC.md` — long-duration household methodology.

That system remains canonical for mixed/long household recordings and release scoring.

New Android-side work on the current branch:

- `WakeBenchmarkHarness.kt` — short/device same-PCM replay helper; sample-time scoring; no microphone;
- `WakeBenchmarkRecords.kt` — Android JSONL records aligned to the existing v4 truth/detection contract plus deterministic threshold-preview utilities;
- `WakeDiagnosticCaptureBuffer.kt` — bounded in-memory candidate/manual-miss pre/post-roll capture using `AudioEngine.readPreRoll`; no second continuous ring, no filesystem I/O, no microphone ownership;
- JVM tests for all three areas.

The Android diagnostic capture only returns an in-memory clip. Raw audio persistence must remain explicit and consent/retention-gated by a diagnostic surface.

A normal CI run initially exposed two stale test expectations after optional JSON fields were hardened from `null` to omission. The assertions were corrected; current wake-infrastructure changes are being reverified. This was a test-contract mismatch, not a microphone/PCM architecture failure.

## openWakeWord evidence already available

Do not restart openWakeWord research from zero.

`wakeword/OPENWAKEWORD_REAL_REPLAY_EVIDENCE.md` already records a successful deterministic compatibility replay using:

- `openwakeword==0.6.0`;
- CPU ONNX runtime;
- pinned official feature models;
- pinned classifier/model provenance;
- explicit NumPy initialization seed to neutralize openWakeWord's randomized feature-buffer priming;
- three-repeat deterministic replay.

This proves compatibility of the existing Okja model/replay path, **not production wake quality**. The next openWakeWord work is Android caller-owned PCM inference plus comparison on the canonical benchmark, not another generic library feasibility probe.

## Execution order

### Task E0 — Android wake evidence bridge — CURRENT

1. verify `WakeBenchmarkHarness`, v4-aligned JSONL records, and bounded diagnostic capture in CI;
2. keep `v4_eval.py` / `v4_benchmark_schema.json` as canonical long-duration scoring and schema;
3. connect future Android detector candidates to these records without introducing automatic raw-audio retention.

Pass condition: Android JVM tests and normal build green; identical replay remains deterministic; no new `AudioRecord` owner; emitted JSON is valid under the existing v4 contract.

### Task E1 — Stage-A wake bake-off

1. adapt openWakeWord inference to Android **caller-owned PCM** using the already-proven model/feature pipeline;
2. implement Porcupine low-level PCM benchmark control without `PorcupineManager`/microphone ownership;
3. compare `옥자야` and `옥자` on identical PCM and Fold4;
4. feed candidate/near-threshold clips into the canonical v4 evaluator and later Stage-B training set.

Initial measurements:

- recall / FRR;
- false activations/hour;
- P50/P95 latency;
- TV/background robustness;
- self-TTS candidate/false activation rate;
- CPU/PSS.

Do not pick the final engine from a short positive-only test.

### Task E2 — Stage-B phrase verification

Train/implement a higher-precision verifier using true wakes plus Stage-A false candidates/hard negatives.

Pass condition: materially reduce false activations without unacceptable recall loss on the same frozen benchmark corpus.

### Task F — hybrid physical-command authorization

Benchmark Moonshine transcript evidence against a constrained physical-command verifier/classifier focused on target + action minimal contrasts.

Required release behavior:

- opposite-action execution: **0 observed**, release-blocking;
- wrong-target execution: **0 observed**, release-blocking;
- false physical execution from non-command/false wake: **0 observed**, release-blocking;
- uncertain/conflicting evidence: abstain/ask again;
- representative command correctness target remains **>=98%**, while wrong-action rate is more important than raw accuracy.

### Task G — end-to-end PCM integration

After wake and command-recognition gates are credible:

`AudioEngine -> Stage A/B wake -> pre-roll/live PCM -> ASR/command verifier -> VoiceSessionController -> deterministic router -> TTS`

### Task H — production migration

Only after the above gates:

- migrate `MainActivity`;
- remove old Gate -> release -> `SpeechRecognizer` production topology;
- add Android microphone foreground-service lifecycle through visible/user-authorized start;
- split diagnostic and release surfaces;
- run long positive/negative soak tests.

## Current blocker

There is no external/user blocker.

The active engineering gate is CI verification of the Android wake evidence bridge, followed by the Android caller-owned-PCM openWakeWord path. No user hardware input is required until a new benchmark APK is ready.

## Documentation hierarchy

1. `STATUS.md` — implemented state and next actions.
2. `ARCHITECTURE.md` — target architecture.
3. `architecture/ADR-*.md` — accepted decisions and rationale.
4. `SECURITY_BACKLOG.md` — deferred security/release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology and candidate status.
6. `wakeword/AIHUB_V4_HOUSEHOLD_BENCHMARK_SPEC.md` + v4 schema/evaluator — canonical wake evidence contract.
7. Historical `AIHUB_*.md` / diagnostic notes — evidence only.
