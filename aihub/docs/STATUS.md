# Project Okja — Current Status

Last updated: 2026-08-20 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WAITING — SENSEVOICE MODEL-PROVISIONED BENCHMARK ARTIFACT**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`

### Last completed

- Single-owner PCM architecture implemented and unit-tested.
- PCM continuity/discontinuity fail-closed handling implemented.
- Same-PCM ASR benchmark harness implemented.
- Fold4 Moonshine vs Zipformer corpus reviewed.
- Benchmark semantic-command scoring corrected (`TV` / `티비` aliases only; action inversions remain failures).
- SenseVoice 2025 Korean-capable comparator added.
- Benchmark Activity changed to Moonshine + SenseVoice by default.
- Per-trial JSON plus aggregate `summary.json` added.
- Latest lightweight Android/JVM verification for the new Activity: run `#235` / `32326420960` — success.

### Current

The model-provisioned workflow has been changed from Moonshine + Zipformer to:

1. `sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27`
2. `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`

The workflow provisions both official model archives, records archive/file SHA-256 benchmark provenance, builds the APK, and uploads the APK plus provenance as a GitHub Actions artifact.

### Blocker

No architecture or code blocker.

No user input is needed until the new model-provisioned APK artifact is verified. The next user-side action will be a small Fold4 same-PCM comparison using the same three benchmark phrases.

## Current architecture

- `AudioEngine` is the sole production `AudioRecord` owner.
- Canonical audio: 16 kHz, mono, PCM16, 20 ms frames.
- Wake/VAD/ASR/diagnostics consume shared PCM and must not acquire the microphone independently.
- `PcmRingBuffer` supplies pre-roll without microphone handoff.
- `PcmFrame` carries monotonic sequence/sample-position metadata.
- `PcmContinuityTracker` and `UtteranceAudioIntegrityGate` detect/fail closed on PCM loss.
- Deterministic device routing stays ahead of generative AI.
- Android `SpeechRecognizer` / Mode F remains compatibility evidence, not the continuous production path.

## Source revalidation

The ASR plan was rechecked against current Android documentation and current sherpa-onnx upstream before SenseVoice integration.

Relevant current upstream facts:

- sherpa-onnx v1.13.4 Kotlin API includes `OfflineSenseVoiceModelConfig`;
- v1.13.4 helper model type `41` maps to `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`;
- current sherpa-onnx SenseVoice documentation lists Korean support and Android simulated-streaming/VAD+ASR usage;
- Android `SpeechRecognizer` remains unsuitable as the target continuous production ASR architecture.

## Fold4 baseline corpus

The original benchmark contains exactly three phrases:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

All three phrase categories are present repeatedly in the supplied device evidence. There is no need to block progress on locating an additional screenshot merely to prove phrase coverage.

Across the 10 unique saved runs visible in the supplied screenshots:

### Moonshine tiny-ko

- non-empty positive output: **10/10**
- semantic suffix preserved overall: **7/10 (70%)**
- conversational `뭐하니`: **4/4**
- physical device commands (`TV 켜줘`, `에어컨 꺼줘`): **3/6 (50%)**
- mean init: **~625 ms**
- mean replay/decode: **~160 ms**

Important hard failures included:

- `TV 켜줘` -> `TV 꺼줘`
- `에어컨 꺼줘` -> `에어컨 꺼져`
- one unusable AC transcription (`복잡해요. 큰 꺼져.`)

Moonshine therefore remains the best observed candidate so far, but is **not production-ready for physical device commands**.

### Korean streaming Zipformer

- non-empty positive output: **9/10**
- positive-case `<EMPTY>` failure: **1/10**
- semantic suffix preserved overall: **4/10 (40%)**
- conversational `뭐하니`: **4/4**
- physical device commands: **0/6 (0%)**
- mean init: **~1344 ms**
- mean replay/decode: **~433 ms**

Decision: Zipformer is no longer a primary candidate. Keep it only as historical/fail-fast comparison evidence unless upstream Android behavior materially changes.

## Benchmark metric rules

Transcript fidelity and command preservation are separate metrics.

Allowed device-token equivalence is intentionally narrow:

- `TV`
- `티비`
- `티브이`
- `텔레비전`

Action changes are never normalized away. Examples that remain failures:

- `켜줘` -> `꺼줘`
- `꺼줘` -> `꺼져`

A device command must therefore preserve the intended target and action, not merely produce plausible Korean text.

## Current SenseVoice work

Implemented on the feature branch:

- `SherpaSenseVoiceBenchmarkEngine`
- official SenseVoice 2025 model provisioning script
- SHA-256 benchmark provenance recording
- Moonshine + SenseVoice default benchmark pair
- Zipformer removed from default new trials
- trial counter
- aggregate per-engine suffix/silent-failure summary
- `summary.json` export
- scrollable result UI for larger benchmark output

Key commits:

- `05c1b9b5a5123cf767211a2b4dd7c65565a6a635` — SenseVoice PCM-only adapter
- `a3c3253aa5a57d80115d2243d5b7940e719bcc9a` — SenseVoice model provisioning
- `5d2f86f2cf5ad7293f1a267ffd1d7feeaefdab74` — Fold4 Moonshine/SenseVoice benchmark Activity + summary
- `70d7c233f52fde8e030456a9362eb3bf5b7f3763` — current model-provisioned workflow pair

## Next execution order

### Task C2 — verify model-provisioned Moonshine/SenseVoice APK — NEXT

- confirm official SenseVoice archive download succeeds in CI;
- confirm Android packaging succeeds with the additional large model;
- record APK SHA-256 and model provenance;
- review build logs/artifact before asking for a device test.

### Task C3 — minimal Fold4 comparator

Once the APK is verified, run one pass each of the original three phrases:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

The same captured PCM in each trial is decoded by Moonshine and SenseVoice. Compare:

- semantic suffix preservation;
- action inversion rate;
- silent failures;
- model init;
- decode latency.

Do not ask for dozens of manual repetitions until this first three-phrase SenseVoice gate shows whether the model is worth continuing.

### Task D — VoiceSessionController

After the local-ASR comparator is resolved:

- move voice lifecycle authority out of `MainActivity`;
- preserve already-captured command suffixes;
- enforce one capture owner / one utterance decode path;
- reject stale callbacks and bound retries;
- make MIC_OFF/TTS transitions deterministic;
- require clean PCM integrity before physical command authorization.

### Task E — wake benchmark

1. Porcupine low-level PCM Korean/custom wake baseline.
2. sherpa KWS only if Korean model/tokenization evidence is established.

Wake correctness is evaluated independently from whether ASR transcribes `옥자` correctly.

### Task F — production migration

After ASR/wake acceptance:

- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove old Gate -> release -> `SpeechRecognizer` production topology;
- add current-Android microphone foreground-service lifecycle through a visible/user-authorized start flow;
- separate diagnostic and release build surfaces.

Later release gates remain tracked separately: dedicated repo extraction (#22), deferred security work (#21), and legacy-doc archive (#25).

## Documentation hierarchy

1. `STATUS.md` — current state and next actions.
2. `ARCHITECTURE.md` — intended architecture.
3. `architecture/ADR-*.md` — decision rationale.
4. `SECURITY_BACKLOG.md` — deferred security/release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology.
6. Historical `AIHUB_*.md` and diagnostic notes — evidence only.
