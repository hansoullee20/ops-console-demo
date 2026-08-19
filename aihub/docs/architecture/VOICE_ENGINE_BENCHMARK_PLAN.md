# Okja Voice Engine Benchmark Plan

Revalidated: 2026-08-19 against current Android platform documentation and actively maintained upstream voice projects.

All engines must receive the same recorded PCM corpus. Microphone behavior is benchmarked separately on-device.

## ASR architecture decision

Android `SpeechRecognizer` remains a compatibility/fallback experiment, not the production continuous-ASR architecture. Android's current API documentation states that the service is not intended for continuous recognition, and `EXTRA_AUDIO_SOURCE` remains implementation-dependent: a recognizer that does not support it may open the microphone itself.

The production direction therefore remains local PCM-fed ASR behind Okja's single-owner `AudioEngine`.

## ASR candidates and order

### 1. sherpa-onnx Moonshine tiny-ko v2 — primary first benchmark

Model: `sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27`

Current sherpa-onnx documents Korean Moonshine v2 for Android and VAD + ASR / real-time or simulated-streaming usage. In Okja, the first adapter is utterance-scoped: it buffers bounded pre-roll + live PCM and performs offline decode at utterance end. It therefore has final latency but no native partial-token latency in this adapter.

Use it as the first Korean local baseline because it is current and has an official Android/VAD path.

### 2. sherpa-onnx Korean streaming Zipformer — short fail-fast smoke, then benchmark only if healthy

Model: `sherpa-onnx-streaming-zipformer-korean-2024-06-16`

Do not assume this model is the preferred engine simply because it compiles. Upstream issue `k2-fsa/sherpa-onnx#2886` remains open and reports both Korean streaming variants returning empty transcription on Android while model loading and audio processing appear successful.

Okja's benchmark result therefore records `recognitionExpectedButEmpty`. On Fold4, run a short positive smoke first. If the v1.13.4 runtime still returns empty output, record the reproduction and remove Zipformer from the primary benchmark rather than spending time tuning the audio pipeline around a silent model.

### 3. Android SpeechRecognizer via `EXTRA_AUDIO_SOURCE` — compatibility control only

Retain Mode F only to measure:

- whether the Fold4 recognizer honors caller-supplied PCM;
- whether it opens a second microphone capture session;
- connected-utterance preservation;
- system recognition cue behavior.

Passing Mode F does not promote Android SpeechRecognizer to the production continuous-ASR architecture.

### 4. Optional fallback: sherpa SenseVoice

If both dedicated Korean candidates are unsuitable, SenseVoice is a reasonable later local baseline because current sherpa-onnx supports Korean among its languages and provides VAD + ASR examples. Do not add it before the Moonshine/Zipformer smoke results justify another candidate.

## ASR measurements

Measure per engine where technically applicable:

- full-utterance preservation for connected `옥자야 + command`;
- exact command-suffix preservation;
- exact transcript match plus WER/CER on the real corpus;
- explicit positive-case empty-output failures;
- first partial latency for engines that expose partials;
- final latency;
- wake-event to first usable transcript/token when integrated;
- PCM discontinuity count;
- CPU;
- peak PSS/RSS;
- 30 min and 8 h thermal/battery behavior.

A missing partial is not automatically a failure for utterance-scoped Moonshine; final latency and command accuracy are the relevant first metrics for that adapter.

## Wake candidates

### 1. Porcupine low-level PCM API — Android-ready baseline

Use the low-level API only. `Porcupine.process()` accepts caller-owned PCM, while `PorcupineManager` owns integrated microphone capture and therefore violates Okja's one-microphone-owner architecture.

Porcupine requires an AccessKey, so it is a benchmark baseline rather than a commitment to the final licensing/dependency choice.

### 2. sherpa-onnx KWS — research candidate, not yet Korean-ready by assumption

sherpa-onnx has an Android keyword-spotting app and open-vocabulary KWS, but its current documented pretrained KWS models/APKs are Chinese and English. Do not treat sherpa KWS as a ready Korean `옥자` production engine until a Korean-capable model/tokenization path is demonstrated with evidence.

### 3. openWakeWord — lower-priority research path

Keep as a later option if the first two candidates are insufficient. Do not spend the current milestone porting a Python-centered stack to Android before measuring Android-ready alternatives.

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

- connected wake+command continuity >= 98/100;
- duplicate command execution = 0;
- final local path system recognition cue = 0;
- one active `AudioRecord` throughout wake -> ASR;
- positive ASR cases must not silently return empty output;
- false activation target <= 0.2/hour in the first long-negative wake gate.

Mode F remains a short compatibility test and cannot become the production architecture merely by passing these gates.

## Runtime optimization order

Use CPU / standard ONNX Runtime first. QNN/NPU work is a later optimization after accuracy, continuity, and lifecycle correctness are proven on Fold4; current accelerator/model support changes quickly and should not drive the first production architecture.

## Model provenance

Provisioning scripts record downloaded archive and selected-file SHA-256 hashes and can reject an archive when `OKJA_MODEL_SHA256` is supplied. A first-seen digest is benchmark provenance, not a trust anchor. Before a release candidate, promote reviewed model digests into a pinned release manifest rather than downloading mutable native/model artifacts without verification.
