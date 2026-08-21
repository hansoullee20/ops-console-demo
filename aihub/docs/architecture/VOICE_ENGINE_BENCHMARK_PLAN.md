# Okja Voice Engine Benchmark Plan

Revalidated: 2026-08-21 against current Fold4 evidence and the verified `VoiceSessionController` core.

All recognition engines must receive the same recorded PCM when compared. Microphone behavior is benchmarked separately on-device.

## Architecture decision

Android `SpeechRecognizer` remains a compatibility/fallback experiment, not the target continuous-recognition architecture.

The production direction remains one `AudioEngine` microphone owner with all wake/VAD/ASR/command-recognition components consuming supplied PCM.

## Current recognition candidate status

### 1. sherpa-onnx Moonshine tiny-ko — incumbent full-ASR baseline

Model: `sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27`

Observed Fold4 evidence:

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

Moonshine remains the fastest and strongest observed local full-ASR baseline, but it is **not production-approved for physical device execution** because action inversions and unrelated transcriptions have occurred.

### 2. sherpa-onnx SenseVoice 2025 — rejected primary candidate

Model: `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`

Okja adapter configuration:

- explicit `language = "ko"`;
- inverse text normalization disabled;
- caller-owned PCM only.

Five Fold4 same-PCM trials:

- semantic suffix: **0/5**;
- physical device commands: **0/4**;
- silent failures: **0/5**, but returned text was unusable CJK/mixed-script output;
- mean init: **1978.2 ms**;
- mean replay/decode: **325.0 ms**.

Decision: stop manual SenseVoice collection. Retain the adapter and evidence only for historical/debug use unless upstream behavior changes materially.

### 3. Korean streaming Zipformer — rejected primary candidate

Model: `sherpa-onnx-streaming-zipformer-korean-2024-06-16`

Observed Fold4 evidence:

- semantic suffix: **4/10**;
- physical device commands: **0/6**;
- positive `<EMPTY>` failure: **1/10**;
- mean init: **~1344 ms**;
- mean replay/decode: **~433 ms**.

Decision: historical/fail-fast evidence only.

### 4. Android SpeechRecognizer / external-audio experiments — compatibility control only

Use only to investigate platform behavior or compare system recognizer characteristics. Passing an external-audio experiment does not make it the continuous production recognizer.

## Physical-command strategy gate

The current evidence does **not** support authorizing physical actions from unrestricted full-ASR text alone.

The next command-safety benchmark should compare the incumbent Moonshine path against one or more constrained/hybrid approaches when implementation research justifies them, for example:

- command-specialized acoustic intent classifier;
- second-pass action-word verifier;
- constrained command grammar;
- confidence/ambiguity abstention;
- joint scoring between ASR and deterministic command candidates.

The benchmark priority is not generic WER. It is correct target/action preservation with near-zero wrong physical execution.

If a verifier disagrees with ASR on an action such as `켜` versus `꺼`, the system should reject/ask again rather than execute.

## Corpus

Core connected-utterance phrases remain:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

The three-phrase set is a fail-fast device gate, not a production acceptance corpus.

Any new recognition approach should first run the same three phrases on identical PCM before expanding to a larger corpus.

A larger acceptance corpus must add minimal-contrast and negative cases, including:

- `켜` / `꺼`;
- `켜줘` / `꺼줘`;
- `꺼줘` / `꺼져`;
- negated commands;
- target substitutions;
- wake-only speech;
- conversational speech containing device words without a command.

## Command scoring rules

Transcript fidelity and device-command preservation remain separate metrics.

Tiny allowed target alias set:

- `TV`;
- `티비`;
- `티브이`;
- `텔레비전`.

Punctuation/spacing differences do not by themselves fail a semantic suffix.

Action changes are hard failures and must never be normalized away:

- `켜줘` -> `꺼줘`;
- `꺼줘` -> `꺼져`.

Production authorization independently validates target/action and PCM integrity. Benchmark normalization is not authorization logic.

## Recognition measurements

Measure where applicable:

- connected-utterance preservation;
- semantic command-suffix preservation;
- action inversion count;
- wrong-target count;
- abstention/rejection rate;
- false physical execution rate;
- transcript exactness / CER on larger corpora;
- positive-case empty outputs;
- model cold init;
- warm/final decode latency;
- CPU;
- peak PSS/RSS;
- thermal/battery impact after correctness passes.

For physical commands, a rejected uncertain command is preferable to a wrong action.

## Closed Fold4 SenseVoice gate

The five-run device gate is complete.

Final observed comparison:

| Metric | Moonshine | SenseVoice 2025 |
|---|---:|---:|
| Semantic suffix | 4/5 | 0/5 |
| Physical commands | 3/4 | 0/4 |
| Mean init | 616.8 ms | 1978.2 ms |
| Mean decode | 155.2 ms | 325.0 ms |

Decision: SenseVoice is not a current production candidate. Do not request more Fold4 repetitions for this pair.

## VoiceSessionController verification gate

The ASR-agnostic controller core is implemented and verified.

CI run `#259` / `32358751275` completed successfully with:

- deterministic pre-build failure matrix;
- Android JVM tests;
- debug APK build;
- artifact upload.

Controller tests cover:

- exactly-once physical execution for a current generation;
- fail-closed behavior after PCM discontinuity;
- stale-generation frame rejection;
- stale TTS callback rejection;
- TTS recursion blocking;
- bounded recoverable failures and explicit degraded recovery.

The next benchmark work should not re-open controller fundamentals unless integration exposes a real failure.

## Wake candidates

### 1. Porcupine low-level PCM API — first benchmark candidate

Use the low-level PCM API only. Integrated microphone-manager APIs violate the one-microphone-owner invariant.

Benchmark both `옥자` and a longer `옥자야` form if custom keyword tooling permits it.

Porcupine requires an AccessKey, so this is a benchmark baseline rather than a final licensing commitment.

### 2. sherpa-onnx KWS — research candidate

Do not assume Korean readiness until a Korean-capable model/tokenization path is demonstrated.

### 3. Other PCM-fed wake engines

Evaluate only if they have credible Android ARM64/raw-PCM support and can be benchmarked without acquiring the microphone.

## Wake measurements

- false reject rate;
- false activations/hour;
- keyword-end to detection latency;
- CPU / PSS;
- TV/background-speech robustness;
- quiet/elderly-speaker robustness;
- TTS self-trigger rate;
- effect of short `옥자` vs longer `옥자야` trigger.

## Initial production-oriented gates

Target: Galaxy Z Fold4 / SM-F936N.

Architecture gates:

- one active `AudioRecord` throughout wake -> recognition;
- duplicate physical command execution = **0**;
- production path system recognition cue = **0**;
- PCM-discontinuous utterance physical execution = **0**.

Recognition gates should separate success from dangerous errors:

- connected command correctness: target **>= 98%** on the final representative corpus;
- wrong opposite-action execution: target **0 observed** in acceptance/soak testing and treated as release-blocking;
- false physical execution from non-command/false wake: release-blocking;
- uncertain/conflicting recognition should abstain rather than guess.

Wake initial gate:

- false activation target **<= 0.2/hour** in the first long-negative benchmark, subject to adjustment after realistic home-environment measurement.

These thresholds are engineering gates, not claims that the current small corpus proves production reliability.

## Runtime optimization order

Use CPU / standard runtime first.

QNN/NPU/other acceleration is a later optimization after command correctness, wake reliability, continuity, lifecycle, and battery gates pass.

## Model provenance

Provisioning scripts record archive and selected-file SHA-256 hashes. First-seen digests are benchmark provenance, not release trust anchors.

Before a release candidate, reviewed model/runtime digests must be promoted into a pinned release manifest.
