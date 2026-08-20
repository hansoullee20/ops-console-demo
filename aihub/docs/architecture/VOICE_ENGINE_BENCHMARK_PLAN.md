# Okja Voice Engine Benchmark Plan

Revalidated: 2026-08-20 against current Android platform documentation and current sherpa-onnx/Picovoice upstream sources.

All ASR engines must receive the same recorded PCM. Microphone behavior is benchmarked separately on-device.

## ASR architecture decision

Android `SpeechRecognizer` remains a compatibility/fallback experiment, not the target continuous-ASR architecture. The production direction is local PCM-fed ASR behind Okja's single-owner `AudioEngine`.

The Android API remains implementation-dependent for externally supplied audio, and the platform recognizer is not treated as an always-listening continuous recognizer.

## Current ASR candidate order

### 1. sherpa-onnx Moonshine tiny-ko v2 — incumbent local baseline

Model: `sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27`

Current status from Fold4 evidence:

- 10/10 non-empty positive outputs in the visible corpus;
- 7/10 semantic suffix preservation overall;
- 4/4 conversational suffix preservation;
- only 3/6 physical-device command suffix preservation;
- mean init about 625 ms;
- mean replay/decode about 160 ms.

Moonshine remains the best observed candidate so far, but action inversions such as `켜줘 -> 꺼줘` make it unsuitable for production device control without a better comparator/result.

### 2. sherpa-onnx SenseVoice 2025 — active comparator

Model: `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`

Why it is active now:

- current sherpa-onnx documentation explicitly lists Korean support;
- current Android/simulated-streaming/VAD+ASR examples exist;
- sherpa-onnx v1.13.4 Kotlin API contains `OfflineSenseVoiceModelConfig`;
- v1.13.4 helper model type `41` maps to this 2025 model;
- Moonshine's first Fold4 physical-command result (3/6) is not sufficient to select it without another current local comparator.

Okja's first adapter is utterance-scoped/offline decode over caller-owned PCM. It must never acquire the microphone.

### 3. Korean streaming Zipformer — historical/fail-fast evidence only

Model: `sherpa-onnx-streaming-zipformer-korean-2024-06-16`

Observed Fold4 result:

- 4/10 semantic suffix preservation overall;
- 0/6 physical-device command suffix preservation;
- one positive `<EMPTY>` failure;
- about 1344 ms mean init and 433 ms mean replay/decode.

Decision: remove it from default new trials. Retain code/evidence only for regression comparison or a future materially changed upstream Android runtime/model.

### 4. Android SpeechRecognizer via `EXTRA_AUDIO_SOURCE` — compatibility control only

Retain Mode F only to measure:

- whether the Fold4 recognizer honors caller-supplied PCM;
- whether it opens a second microphone capture session;
- connected-utterance preservation;
- system recognition cue behavior.

Passing Mode F does not promote Android SpeechRecognizer to the production continuous-ASR architecture.

## Corpus

The initial Fold4 phrase set is exactly:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

All three categories are already represented repeatedly in the baseline Moonshine/Zipformer evidence.

For a new ASR candidate, start with **one pass of each phrase** before asking for a large manual corpus. Continue only if those first three same-PCM trials justify it.

## Command-scoring rules

Transcript fidelity and device-command preservation are separate metrics.

The semantic device-token alias set is deliberately tiny:

- `TV`
- `티비`
- `티브이`
- `텔레비전`

Punctuation/spacing differences do not by themselves fail a device suffix.

Action changes remain hard failures and must never be normalized away. Examples:

- `켜줘` -> `꺼줘`
- `꺼줘` -> `꺼져`

This scoring rule is for benchmark classification only. The production deterministic router/authorization boundary must independently validate target/action and reject ambiguous transcripts.

## ASR measurements

Measure per engine where technically applicable:

- full connected-utterance preservation;
- semantic command-suffix preservation;
- transcript exactness plus WER/CER on a larger corpus;
- explicit positive-case empty-output failures;
- action inversion count;
- first partial latency for engines that expose partials;
- final/replay decode latency;
- model cold-init latency;
- PCM discontinuity count;
- CPU;
- peak PSS/RSS;
- thermal/battery behavior after the accuracy gate passes.

A missing partial is not automatically a failure for utterance-scoped Moonshine or SenseVoice adapters; final accuracy and command latency are the initial metrics.

## Current Fold4 SenseVoice gate

After the model-provisioned APK is verified, run one same-PCM trial for each original phrase.

Continue SenseVoice benchmarking only if:

- no positive silent-empty failure occurs;
- physical-command suffix preservation is at least competitive with Moonshine;
- it does not introduce action inversions that make the route less safe;
- device latency/memory are plausible for the Fold4 target.

If SenseVoice is clearly worse on the first three trials, stop and retain Moonshine as incumbent while researching another Korean candidate rather than collecting unnecessary repetitions.

## Wake candidates

### 1. Porcupine low-level PCM API — Android-ready baseline

Use the low-level PCM API only. Integrated microphone-manager APIs do not fit Okja's one-microphone-owner topology.

Porcupine requires an AccessKey, so it is a benchmark baseline rather than a commitment to the final licensing/dependency choice.

### 2. sherpa-onnx KWS — research candidate

Do not assume Korean readiness until a Korean-capable model/tokenization path is demonstrated with evidence.

### 3. openWakeWord — lower-priority research path

Keep as a later option if Android-ready alternatives do not meet the wake gate.

## Wake measurements

- false reject rate;
- false activations/hour;
- keyword-end to detection latency;
- CPU / PSS;
- TV/background-speech robustness;
- elderly/quiet-speaker robustness;
- TTS self-trigger rate.

## Initial device gates

Target: Galaxy Z Fold4 / SM-F936N.

- connected wake+command continuity >= 98/100 after final pipeline integration;
- duplicate command execution = 0;
- final local path system recognition cue = 0;
- one active `AudioRecord` throughout wake -> ASR;
- positive ASR cases must not silently return empty output;
- action inversions must be rejected before device execution;
- false activation target <= 0.2/hour in the first long-negative wake gate.

## Runtime optimization order

Use CPU / standard ONNX Runtime first. QNN/NPU work is a later optimization after accuracy, continuity, lifecycle correctness, and battery gates are proven on Fold4.

## Model provenance

Provisioning scripts record downloaded archive and selected-file SHA-256 hashes and can reject an archive when `OKJA_MODEL_SHA256` is supplied. A first-seen digest is benchmark provenance, not a trust anchor. Before a release candidate, promote reviewed model digests into a pinned release manifest.
