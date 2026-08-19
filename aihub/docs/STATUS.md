# Project Okja — Current Status

Last updated: 2026-08-19 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WORKING — TARGET-DEVICE BENCHMARK PREPARATION**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`
Root-cause checkpoint preserved in history: `8cc9897d6c5898c9ccd5be73599ef91c35f01659`

Latest reviewed runtime-code head before this status update: `4c3c77d1ddc504c2d749d0135c652e8f07936399`
Verified normal CI for that code: run `#208` / `32247316507` — success (failure matrix, JVM tests, debug APK build, artifact upload).

A separate model-provisioned benchmark APK workflow is now tracked as `Build Okja local ASR benchmark APK`; its first PR-visible run is run `#3` / `32247367868`.

## 2026-08 current-source revalidation

The execution order was rechecked against current Android platform documentation and actively maintained sherpa-onnx / Picovoice upstream sources before continuing.

The architecture remains correct:

- exactly one `AudioRecord` owner (`AudioEngine`);
- wake/VAD/ASR consume caller-owned PCM;
- ring-buffer/pre-roll continuity replaces microphone handoff;
- deterministic device routing precedes generative AI;
- Android SpeechRecognizer is compatibility evidence, not the continuous production ASR.

Two implementation priorities changed:

1. `sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27` is now the first primary Korean local-ASR benchmark.
2. Korean streaming Zipformer is now a short fail-fast Fold4 smoke before any long benchmark because upstream issue `k2-fsa/sherpa-onnx#2886` remains open and reports empty Android transcription from both Korean streaming variants.

Wake priority also changed: Porcupine low-level PCM is the Android-ready Korean baseline. sherpa KWS remains a research candidate until a Korean-capable model/tokenization path is demonstrated; the currently documented pretrained KWS models/APKs are Chinese/English.

## Established audio architecture

- `AudioEngine` is the only production microphone owner.
- Canonical audio is 16 kHz, mono, signed PCM16, 20 ms frames.
- `PcmRingBuffer` provides bounded pre-roll without releasing/reacquiring the microphone.
- Wake/VAD/ASR/diagnostics are PCM consumers and must not create their own `AudioRecord`.
- `PcmFrame` carries monotonic sequence/sample-position metadata.
- `PcmContinuityTracker` detects dropped/out-of-order audio.
- `UtteranceAudioIntegrityGate` fails closed after a capture gap until a clean utterance begins.

Issue #24 remains open only for wiring this integrity gate into the future transcript -> physical-device authorization path.

## Completed / reviewed engineering work

### 1. Same-PCM replay core

`AsrBenchmarkHarness`:

- replays identical PCM into interchangeable ASR engines;
- preserves canonical frame sequence/sample-position metadata;
- measures transcript/suffix preservation and replay timing;
- has a regression test ensuring latency is relative to the explicit monotonic replay origin;
- reports `recognitionExpectedButEmpty` so a positive case that silently produces no text cannot look like success.

Review after implementation caught and fixed the original absolute-clock latency bug.

### 2. Korean Zipformer adapter

`SherpaStreamingAsrEngine`:

- uses pinned sherpa-onnx Android runtime `v1.13.4`;
- consumes only supplied PCM/pre-roll;
- owns no microphone;
- uses the official Korean streaming model configuration.

It remains in the codebase for a short Fold4 smoke, but is no longer presumed to be the preferred production engine because of the current upstream empty-output issue.

### 3. Korean Moonshine benchmark adapter

`SherpaMoonshineBenchmarkEngine`:

- uses current sherpa-onnx Korean Moonshine tiny-ko v2 model type `51`;
- consumes supplied pre-roll + live PCM only;
- buffers one bounded utterance in `Pcm16UtteranceBuffer`;
- fails on buffer overflow rather than silently truncating command speech;
- performs utterance-end offline decode and therefore intentionally exposes final-only output in this first adapter;
- owns no microphone.

This is compatible with the target architecture: VAD can establish utterance boundaries while both VAD and Moonshine consume the same PCM bus.

### 4. Model provenance tooling

Provisioning scripts now exist for Moonshine tiny-ko and Korean streaming Zipformer.

They:

- download from official sherpa-onnx release locations;
- record archive SHA-256;
- record selected model-file SHA-256 hashes;
- optionally enforce an expected `OKJA_MODEL_SHA256`;
- explicitly warn that a first-seen digest is benchmark provenance, not a release trust anchor.

Release-grade model hash pinning remains future work after the benchmark candidate is selected.

### 5. Fold4 same-PCM benchmark Activity

`LocalAsrBenchmarkActivity` now:

- captures one four-second case using `AudioEngine` only;
- validates live capture continuity and fails on a PCM gap;
- stops microphone capture before creating either recognizer;
- saves the raw PCM16 case;
- replays that exact PCM through Moonshine first and Zipformer second;
- records transcript, exact/suffix result, silent-empty failure, model-init time, and replay/decode time to JSON;
- keeps model initialization separate from ASR replay timing.

The Activity is exposed only as an additional launcher entry in the current diagnostic build.

Review history: the first version failed CI because of two Kotlin compile mistakes (`PcmContinuityStatus.reason` and `assetManager`). Those were diagnosed from CI and fixed. A later review also separated cold model initialization from replay/decode timing. Normal CI run #208 is green after those fixes.

## Current benchmark order

### Task A — model-provisioned benchmark APK — ACTIVE

Build an APK containing both official Korean model assets and record APK/model provenance.

Workflow: `.github/workflows/okja-local-asr-benchmark-apk.yml`.

### Task B — first Fold4 trial — NEXT EXTERNAL GATE

Use the `Okja ASR Benchmark` launcher and run exactly one first case:

`옥자야 뭐하니`

The app will capture once and feed the same PCM to:

1. Moonshine tiny-ko;
2. Korean streaming Zipformer smoke.

Do not infer engine quality until this target-device evidence exists.

### Task C — expand same-PCM corpus

If the first trial is healthy, collect repeated connected cases:

- `옥자야 뭐하니`;
- `옥자 TV 켜줘`;
- `옥자 에어컨 꺼줘`;
- quiet speech;
- TV/background negatives.

Measure exact/suffix accuracy, WER/CER where useful, model init, decode/final latency, CPU/PSS, PCM gaps, and later thermal/battery behavior.

If Zipformer reproduces the upstream silent-empty failure on current Fold4/v1.13.4, record it and stop spending primary benchmark time on that model.

### Task D — VoiceSessionController

After at least one PCM-fed local ASR passes the Fold4 gate:

- move lifecycle authority out of `MainActivity`;
- preserve the already-captured command suffix;
- enforce one capture owner / one utterance decoder path;
- reject stale callbacks;
- bound retries;
- make MIC_OFF/TTS transitions deterministic;
- require clean PCM integrity before physical command authorization.

### Task E — wake benchmark

Compare PCM-fed wake candidates without changing microphone ownership:

1. Porcupine low-level Korean/custom wake baseline;
2. sherpa KWS only if Korean support/model evidence is established.

### Task F — production migration and Android lifecycle

After ASR/wake acceptance:

- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove the old Gate -> release -> SpeechRecognizer production path;
- add the microphone foreground-service lifecycle through a visible/user-authorized start flow required by current Android while-in-use microphone restrictions;
- separate diagnostic and release build surfaces.

### Later release gates

- dedicated `project-okja` repository extraction (#22);
- deferred security release gates (#21);
- archive legacy `AIHUB_*.md` after canonical docs remain stable (#25).

## Current blocker

No architecture or compile blocker.

The only meaningful external gate is real Fold4 speech evidence after the model-provisioned benchmark APK is green. Until that trial is performed, do not claim Korean model accuracy, latency, CPU, battery, or production readiness.

## Documentation hierarchy

1. `STATUS.md` — current state and next actions.
2. `ARCHITECTURE.md` — intended production architecture.
3. `architecture/ADR-*.md` — decision rationale.
4. `SECURITY_BACKLOG.md` — known security work and release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — current-source benchmark methodology.
6. Historical `AIHUB_*.md` and diagnostic notes — evidence/context, not current source of truth.
