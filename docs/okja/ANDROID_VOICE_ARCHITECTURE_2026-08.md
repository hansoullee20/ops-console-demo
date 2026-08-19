# Project Okja — Android Voice Architecture (2026-08)

## Status
Architecture decision record based on Fold4 observations and current Android/open-source ecosystem review.

## Decision
Do not use `AudioRecord -> release -> SpeechRecognizer` as the production voice path. The production direction is a **single microphone owner** with a PCM bus/ring buffer, local wake detection, VAD, streaming Korean ASR, deterministic device intents, and AI fallback only when needed.

`SpeechRecognizer + EXTRA_AUDIO_SOURCE` remains a bounded compatibility experiment/fallback, not the primary architecture. Android documents that SpeechRecognizer is not intended for continuous recognition, and EXTRA_AUDIO_SOURCE behavior depends on recognizer support.

## Target pipeline

```text
Microphone
  -> AudioRecord (single owner; PCM16, 16 kHz, mono)
  -> PCM bus + 3–5 s circular buffer
      -> wake detector
      -> VAD
  -> on wake: 1–2 s configurable pre-roll + live PCM
  -> Korean streaming ASR
  -> transcript router
      -> deterministic device intent -> device/Home Assistant adapter
      -> AI fallback -> conversational response
  -> TTS
```

### Invariants
1. Exactly one component owns microphone capture.
2. Wake/VAD/ASR consumers never open the microphone themselves.
3. Wake-to-ASR transition never releases/reacquires AudioRecord.
4. Pre-roll is configurable; ring-buffer capacity is larger than pre-roll.
5. Device commands take a deterministic route before AI fallback.
6. Audio-engine and recognizer implementations are replaceable behind interfaces.

## Android SpeechRecognizer / Mode F
Android API 33+ provides `RecognizerIntent.EXTRA_AUDIO_SOURCE`, a ParcelFileDescriptor for an already-open audio source. The caller supplies encoding/channel/sample-rate metadata and closes the stream. If unsupported, the recognizer may open its own microphone. Android also explicitly states SpeechRecognizer is not intended for continuous recognition and implementations may stream audio remotely.

Mode F therefore exists only to answer a device-specific question: can the installed recognizer consume Okja's buffered+live PCM without taking a second microphone and without clipping the utterance?

### Mode F acceptance gate
Test phrase: `옥자야 뭐하니`, 20 trials on Fold4.

Pass only if:
- >= 19/20 retain the complete intended utterance;
- additional microphone acquisition count = 0;
- no unacceptable recognition cue/UI side effect;
- session termination is deterministic when the supplied audio stream closes.

A failure does not block Okja; it removes SpeechRecognizer from the primary path.

## Primary ASR direction: benchmark-first sherpa-onnx
Current sherpa-onnx Android support includes prebuilt Android libraries/APKs and examples for streaming/non-streaming ASR, VAD, keyword spotting and other speech functions. It remains the preferred **runtime prototype family** because it can consume application-owned PCM without an OS microphone handoff.

However, no single Korean sherpa model is approved as the production default yet. A currently open upstream issue reports that both variants of `sherpa-onnx-streaming-zipformer-korean-2024-06-16` returned empty transcription on Android 1.12.17 despite loading and consuming PCM successfully. This means runtime capability and model viability must be treated separately.

### ASR selection rule
Do not hard-code the 2024 Korean streaming Zipformer as the production model. Maintain adapters so candidate models can be swapped without changing `core-audio` or app lifecycle code. A model becomes production-eligible only after passing the Fold4 corpus gate.

Benchmark at minimum:
- Android SpeechRecognizer Mode F;
- latest viable sherpa Korean streaming model(s);
- latest viable sherpa simulated-streaming/non-streaming Korean model(s) where latency is acceptable;
- any later Korean streaming model that resolves the upstream regression.

Record:
- full-utterance preservation;
- WER / command exact-match rate;
- wake -> first partial latency;
- wake -> final latency;
- CPU;
- peak RSS;
- thermal behavior;
- battery drain;
- model size and cold-start time;
- empty-transcript/error rate.

## Wake-word candidates
### Baseline
Porcupine low-level frame processing is suitable for a custom PCM pipeline. Do not use a high-level microphone-owning manager in the final architecture.

### sherpa-onnx KWS
Architecturally attractive because KWS/VAD/ASR can potentially share one native runtime. Current upstream Android KWS support is real, but Korean wake-word quality must be measured rather than assumed from non-Korean pretrained KWS examples.

### openWakeWord
Keep as an R&D candidate, not first Android integration. Its upstream workflow remains less Android-native than the two candidates above.

## Reference architecture: Home Assistant Assist Satellite
Home Assistant's Assist Satellite uses explicit states equivalent to IDLE, LISTENING, PROCESSING and RESPONDING and exposes wake/VAD/pipeline configuration concepts. Use it as a reference for state-machine and smart-home integration boundaries, not as code to copy blindly.

## Android lifecycle constraint
Always-listening behavior must be designed around modern Android microphone/foreground-service restrictions. Do not assume a background process can freely start microphone capture. Lifecycle, foreground-service notification, permission and restart behavior are part of the product architecture.

## Implementation milestones
### M0 — Preserve evidence
Keep the existing failing handoff implementation and Fold4 observations reproducible until the replacement passes tests.

### M1 — Audio Core
Implement `AudioEngine`, one AudioRecord, canonical PCM format, 3–5 s circular buffer, timestamp/frame counters, consumer fan-out, and capture diagnostics.

### M2 — Engine benchmark harness
Feed identical PCM/corpus into SpeechRecognizer Mode F and sherpa candidates. Produce machine-readable benchmark results. Include explicit detection of empty-transcript failures and model/runtime version metadata.

### M3 — Wake + VAD
Attach wake and VAD as PCM consumers. Compare Porcupine low-level against sherpa KWS where Korean support is viable.

### M4 — Continuous buffered ASR path
On wake, replay configurable pre-roll then continue live frames into ASR with no microphone transition.

### M5 — Intent router
Implement deterministic commands first; only unresolved conversational requests enter the AI agent.

### M6 — Smart-home adapters
Use a narrow adapter boundary for Home Assistant/direct-device APIs so voice code is not coupled to vendor integrations.

### M7 — TTS + barge-in
Add response playback, echo/self-trigger suppression, interruption policy, and state transitions.

### M8 — Reliability
Long-run tests for process death, screen off/lock, network loss, Bluetooth/audio-route changes, thermal load, battery, permission revocation and recognizer/model failure.

## Sources reviewed
- Android Developers: SpeechRecognizer API — continuous-recognition warning and recognizer lifecycle.
- Android Developers: RecognizerIntent.EXTRA_AUDIO_SOURCE — API 33+, supplied PFD audio and fallback behavior.
- sherpa-onnx documentation/repository — Android build/prebuilt binaries, streaming/non-streaming ASR, VAD and KWS applications.
- sherpa-onnx issue #2886 (opened 2025-12-10; still open at 2026-08-19 review) — Korean 2024 streaming Zipformer variants reported empty transcription on Android 1.12.17.
- Home Assistant Assist Satellite developer documentation — explicit satellite states and wake/VAD/pipeline concepts.
- Home Assistant Android 2026 issues — active work around Assist settings/custom wake-word behavior.

## Research caveat
Upstream capabilities change quickly. Model names, binaries and device acceleration must be pinned only after the Fold4 benchmark. Architecture should depend on interfaces and measured behavior, not a particular model release.