# ADR-0004 — Acoustic physical-command authority and first wake benchmark

Status: accepted for implementation

Date: 2026-08-22

Supersedes the physical-command authorization rule and wake-candidate ordering in ADR-0003. ADR-0003 remains historical rationale for single-owner PCM, long-negative wake evaluation, half-duplex TTS, and user-started microphone foreground-service operation.

## Context

Project Okja has target-device evidence that generic Korean ASR is not safe enough to authorize binary household actions.

Fold4 observations:

- Moonshine tiny-ko remains the strongest local full-ASR baseline, but has produced action-critical substitutions including `TV 켜줘 -> TV 꺼줘` and `꺼줘 -> 꺼져`;
- Korean streaming Zipformer and SenseVoice have already failed the target-device comparator gate;
- rejecting an uncertain physical command is cheaper than executing the opposite action.

A general ASR decoder optimizes transcription, not the asymmetric safety cost of `{TV_ON, TV_OFF, AC_ON, AC_OFF}`. Constrained text decoding also cannot prove that the acoustic ON/OFF contrast was heard correctly.

## Decision

### 1. Physical commands use a closed-set acoustic authority

The production physical-command path is:

```text
AudioEngine caller-owned PCM
  -> wake / endpointing
  -> five-class acoustic command model
       {TV_ON, TV_OFF, AC_ON, AC_OFF, OTHER}
  -> calibrated abstention / SafetyGate
  -> deterministic device executor
```

Generic ASR and AI are not actuator authority.

Moonshine remains the conversation/open-language recognizer. An ASR transcript such as `TV 켜줘` is diagnostic/semantic evidence only and cannot mint a physical authorization.

The code expresses this through `PhysicalCommandAuthorizer` / `PhysicalCommandDecision`. The default authorizer rejects all physical commands until a qualified classifier is installed.

### 2. Safety outcomes are semantic, not WER/CER

The command benchmark must report:

- correct;
- abstain;
- wrong device;
- wrong action;
- opposite-action inversion;
- false physical execution from OTHER/background audio.

An opposite-action execution is release-blocking regardless of aggregate accuracy.

### 3. The first wake-engine benchmark is Porcupine 4.0.2 with `옥자야`

The first new wake-engine benchmark candidate is Picovoice Porcupine `porcupine-android:4.0.2` using its low-level caller-owned PCM API, not `PorcupineManager` or any microphone-owning API.

Primary phrase: `옥자야`.

Bare `옥자` remains a comparison/control phrase only because its shorter acoustic form is expected to be more confusable.

For Korean inference the detector explicitly supplies `porcupine_params_ko.pv`. Okja provisions the current pinned upstream Korean parameter file into app-private storage and verifies its upstream Git blob identity before use. The custom Android keyword file is generated through Porcupine's official `trainWakeWordFromPhrase(accessKey, outputPath, "ko", "옥자야")` API and cached privately.

The Picovoice AccessKey is not committed. Keyword/model provisioning may require network once; wake inference after provisioning is local.

This is a benchmark decision, not an assumption that Porcupine has already passed Okja's licensing, false-wake, recall, battery, or Fold4 resource gates.

### 4. No mandatory two-stage wake cascade for v1

A Stage-B phrase verifier is no longer required by architecture before measurement. Add one only if the best single KWS candidate cannot simultaneously meet recall and false-wake gates.

This removes speculative complexity while preserving the option to add a verifier later using real false-positive evidence.

### 5. Endpointing is calibrated before replacing VAD

Keep the 3-second ring buffer, but stop treating a fixed 1.5-second decoder pre-roll as the final slicing policy. Instrument wake sample position, speech onset, action-token retention, and trailing silence. Replace the VAD only if those measurements show the current VAD is the limiting component.

### 6. TTS remains half-duplex for v1

Wake remains disabled while Okja TTS is speaking. Full-duplex/AEC/barge-in remains deferred until the basic command-safety architecture is qualified.

### 7. Physical-classifier runtime is isolated from sherpa-onnx

The Android app already depends on `sherpa-onnx:v1.13.4`. That Android build carries a version-pinned ONNX Runtime native library. Okja therefore does **not** add a second `onnxruntime-android` AAR for the physical-command classifier.

The five-class classifier is exported as TFLite and executed with Google Play services LiteRT (`play-services-tflite-java:16.5.0`) using `FROM_SYSTEM_ONLY`.

Reason:

- avoid two incompatible `libonnxruntime.so` / JNI stacks in one APK;
- keep the tiny protected classifier independent of the conversation-ASR runtime;
- fail closed if the system LiteRT module or classifier cannot initialize.

This changes deployment runtime only. It does not change the acoustic-authority architecture or safety gates.

## Release gates

Initial production qualification targets:

- normal-condition physical-command correctness >= 98%;
- stress-condition correctness >= 95%;
- opposite-action execution: 0 observed in >= 6,000 balanced held-out physical-command trials;
- false physical execution: 0 observed over >= 300 hours of representative household negatives;
- normal-condition wake misses <= 5%;
- false wakes < 0.1/hour;
- action-token clipping: 0 observed in >= 1,000 physical-command utterances;
- no physical execution across PCM or audio-route discontinuity.

Abstention is explicitly preferable to a wrong physical action.

## Implementation order

1. implement semantic physical-command benchmark scoring;
2. move physical execution behind typed acoustic authorization;
3. collect real session/speaker/condition-labeled Fold4 audio and train/calibrate the five-class TFLite classifier;
4. provision/integrate Porcupine 4.0.2 low-level PCM for `옥자야` and benchmark on identical PCM/Fold4;
5. calibrate wake-relative slicing and endpointing;
6. requalify Moonshine for conversation only;
7. harden Android/Samsung lifecycle and run long soak tests;
8. migrate production UI only after safety gates pass.

## Consequences

Positive:

- observed ASR `켜/꺼` inversions can no longer directly actuate a device;
- the benchmark measures the actual product hazard instead of average transcription quality;
- the architecture becomes simpler than ASR + constrained grammar + N-best + separate phoneme verifier by default;
- wake complexity is earned by measurement rather than assumed up front;
- the protected classifier avoids sharing sherpa's native ONNX Runtime.

Costs:

- Okja now owns a small acoustic-classifier dataset/training/calibration task;
- physical commands fail closed until that model is qualified;
- Porcupine introduces a vendor/licensing/AccessKey dependency that must be evaluated before production adoption;
- initial Porcupine Korean provisioning requires network access before subsequent local inference.

## Non-decisions

- Porcupine is not yet production-approved;
- Moonshine is not approved for physical actuation;
- no NPU/QNN optimization is required before the classifier passes semantic safety gates;
- no Stage-B wake verifier is required unless single-engine measurements justify it;
- no full-duplex TTS behavior is required for v1.
