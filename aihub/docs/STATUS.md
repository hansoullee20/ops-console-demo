# Project Okja — Current Status

Last updated: 2026-08-20 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: NEED INPUT — FOLD4 MOONSHINE VS SENSEVOICE THREE-PHRASE GATE**

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
- SenseVoice adapter reviewed: explicit `language = ko`; ITN disabled for Korean command fidelity.
- Normal verification after the final build fix: run `#249` / `32328314338` — success.
- Model-provisioned Moonshine + SenseVoice build: run `#15` / `32328314309` — success.
- Artifact `okja-local-asr-benchmark-apk` independently downloaded and inspected; recorded APK SHA-256 matches the downloaded APK byte-for-byte.

### Model-provisioned build review

The first directly observable Moonshine + SenseVoice model build reproduced an AGP packaging failure at `:app:compressDebugAssets` with `Java heap space`. Both official model downloads had already succeeded. SenseVoice's int8 ONNX file is about 227 MB, so the previous `noCompress` handling alone did not provide enough Gradle heap headroom.

Fix:

- added `aihub/gradle.properties` with `org.gradle.jvmargs=-Xmx4g -Dfile.encoding=UTF-8`;
- retained `.onnx` / `.ort` `noCompress` handling;
- made the model benchmark workflow visible on PR workflow/config changes so the model run can be verified through connected GitHub Actions tooling.

Fix commits:

- `8297a37d8eeb623c3ecd8c65b7422fea4c1f6498` — Gradle heap headroom for large model packaging;
- `5b9c684d4c149da467e23026a8108cca9feedf5a` — model workflow rebuild after heap fix.

Verification:

- model-provisioned run `#15` / `32328314309`: JVM tests, Moonshine provisioning, SenseVoice provisioning, APK build, provenance recording, artifact upload — all success;
- normal run `#249` / `32328314338`: deterministic matrix, Android JVM tests, debug APK build, artifact upload — all success.

### Verified artifact / provenance

Artifact:

- name: `okja-local-asr-benchmark-apk`
- artifact ID: `9392185590`
- artifact bundle size: `254242578` bytes
- artifact bundle digest: `sha256:04c0a670e53c130dfd4adaa055740ef87800d5e154624adaa6278e0bff615842`
- artifact expires: `2026-08-27T03:29:54Z`

APK:

- path inside artifact: `aihub/app/build/outputs/apk/debug/app-debug.apk`
- size: `435926727` bytes
- workflow-recorded SHA-256: `9b293f486db2a7068286cba0bd9261b038f35c4b33725805c4803f7ca2bf1e49`
- independently recomputed SHA-256 after downloading/unzipping the artifact: `9b293f486db2a7068286cba0bd9261b038f35c4b33725805c4803f7ca2bf1e49`

Moonshine model provenance:

- archive: `sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27.tar.bz2`
- archive SHA-256: `d3b6c5390a7859c9ef20ff4f20b0766fcbad1dc06c0f509fe4840a3a302112dc`
- `encoder_model.ort`: `947260d46252f48eada86a34986b3f70c01d68a343959949a77375b94debd055`
- `decoder_model_merged.ort`: `95aa9f2e764b80625d2889d6ec9f05c965808e540ac50c16abd10c7ea33fe44b`
- `tokens.txt`: `2870d843e14c1e187bf1913a521562a63b53933814bd7f2145120468f494a049`

SenseVoice model provenance:

- archive: `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09.tar.bz2`
- archive SHA-256: `7305f7905bfcf77fa0b39388a313f3da35c68d971661a65475b56fb2162c8e63`
- `model.int8.onnx`: `12ca1a2ae7ecf3e0019ef2822307ee0b5cadc9196569e379b4c4026f8205276d`
- `tokens.txt`: `f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc`

The provisioning scripts record first-seen archive hashes but do not yet enforce a release-pinned trust manifest; this is benchmark provenance, not release-grade supply-chain verification.

## Current architecture

- `AudioEngine` is the sole production `AudioRecord` owner.
- Canonical audio: 16 kHz, mono, PCM16, 20 ms frames.
- Wake/VAD/ASR/diagnostics consume shared PCM and must not acquire the microphone independently.
- `PcmRingBuffer` supplies pre-roll without microphone handoff.
- `PcmFrame` carries monotonic sequence/sample-position metadata.
- `PcmContinuityTracker` and `UtteranceAudioIntegrityGate` detect/fail closed on PCM loss.
- Deterministic device routing stays ahead of generative AI.
- Android `SpeechRecognizer` / Mode F remains compatibility evidence, not the continuous production path.

## Fold4 baseline corpus

The original benchmark contains exactly three phrases:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

All three phrase categories are present repeatedly in the supplied Moonshine/Zipformer evidence. There is no need to locate an additional screenshot merely to prove phrase coverage.

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

Moonshine remains the best observed candidate so far, but is **not production-ready for physical device commands**.

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

A device command must preserve the intended target and action, not merely produce plausible Korean text.

## Current SenseVoice work

Implemented on the feature branch:

- `SherpaSenseVoiceBenchmarkEngine`
- explicit Korean language hint and ITN disabled for benchmark fidelity
- official SenseVoice 2025 model provisioning script
- SHA-256 benchmark provenance recording
- Moonshine + SenseVoice default benchmark pair
- Zipformer removed from default new trials
- trial counter
- aggregate per-engine suffix/silent-failure summary
- `summary.json` export
- scrollable result UI for larger benchmark output
- verified model-provisioned APK artifact

Key commits:

- `05c1b9b5a5123cf767211a2b4dd7c65565a6a635` — SenseVoice PCM-only adapter
- `a3c3253aa5a57d80115d2243d5b7940e719bcc9a` — SenseVoice model provisioning
- `5d2f86f2cf5ad7293f1a267ffd1d7feeaefdab74` — Fold4 Moonshine/SenseVoice benchmark Activity + summary
- `e3361d66bfc8cc4c01358f4976943093ddeba203` — review fix: Korean language hint / ITN off
- `8297a37d8eeb623c3ecd8c65b7422fea4c1f6498` — Gradle heap fix for large model packaging
- `5b9c684d4c149da467e23026a8108cca9feedf5a` — verified model build head

## Next execution order

### Task C3 — minimal Fold4 Moonshine/SenseVoice comparator — NEED INPUT

Install the verified APK and run one pass each of the original three phrases:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

The same captured PCM in each trial is decoded by Moonshine and SenseVoice. Compare:

- semantic suffix preservation;
- action inversion rate;
- silent failures;
- model init;
- decode latency.

Do not ask for dozens of repetitions until this three-phrase SenseVoice gate shows whether SenseVoice is worth continuing.

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

## Current blocker

The repository/build side is verified. The next genuine blocker is **Fold4 device input**: one Moonshine-vs-SenseVoice same-PCM pass for each of the three original phrases.

## Documentation hierarchy

1. `STATUS.md` — current state and next actions.
2. `ARCHITECTURE.md` — intended architecture.
3. `architecture/ADR-*.md` — decision rationale.
4. `SECURITY_BACKLOG.md` — deferred security/release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology.
6. Historical `AIHUB_*.md` and diagnostic notes — evidence only.
