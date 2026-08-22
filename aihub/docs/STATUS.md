# Project Okja — Current Status

Last updated: 2026-08-22 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WORKING — PROTECTED COMMAND PATH SCAFFOLDED; REAL FOLD4 DATA + ACCESSKEY-BASED WAKE TEST NEXT**

Repository: `hansoullee20/ops-console-demo`

Branch: `feat/voice-pipeline-v2`

Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`

Latest architecture decision: `architecture/ADR-0004-ACOUSTIC-PHYSICAL-AUTHORITY.md`.

## Production rules now fixed

1. `AudioEngine` is the sole `AudioRecord` owner.
2. Physical commands are authorized by a closed-set acoustic path, never generic ASR/LLM text.
3. Protected classes are `{TV_ON, TV_OFF, AC_ON, AC_OFF, OTHER}` with explicit abstention.
4. Moonshine tiny-ko remains the open-language/conversation ASR baseline only.
5. First wake-engine benchmark: Picovoice Porcupine `4.0.2`, low-level caller-owned PCM, phrase `옥자야`.
6. A mandatory second-stage wake verifier is deferred unless measured false-wake/recall data justifies it.
7. TTS remains half-duplex for v1.
8. MainActivity production migration stays blocked until classifier, wake, endpointing, and lifecycle gates pass.

## Implemented safety boundary

### Physical action authority

`PhysicalCommandSafety.kt` now provides:

- `PhysicalCommandClass`;
- `PhysicalCommandDecision.Authorized` / `Abstain`;
- `PhysicalCommandAuthorizer`;
- reject-all default authorizer;
- explicit semantic safety outcomes including opposite-action inversion and false physical execution.

`VoiceSessionController` feeds caller-owned PCM to both ASR and the physical authorizer, but only an independent typed acoustic authorization may reach `VoiceDeviceCommandExecutor`.

ASR/router `DeviceCommand` output is diagnostic only. A transcript saying `TV 켜줘` is structurally incapable of executing the TV without a physical authorization.

PCM discontinuity, stale generation, authorizer failure, or missing classifier => fail closed.

### Safety benchmark

`PhysicalCommandBenchmarkHarness` replays exact PCM and reports:

- correct;
- abstain;
- wrong device;
- wrong action;
- ON/OFF inversion;
- false physical execution from `OTHER`.

Physical-command qualification no longer depends on WER/CER.

## Fold4 command dataset path

Launcher: **Okja Command Dataset** (`PhysicalCommandDatasetActivity`).

It captures 3.0-second, 16 kHz mono PCM16 samples through `AudioEngine` only and writes:

- raw `.pcm16le`;
- `manifest.jsonl`;
- label;
- prompt;
- speaker ID;
- session UUID;
- acoustic condition;
- device/Android metadata;
- SHA-256;
- PCM-continuity flag.

Hard `OTHER` prompts include ordinary conversation, device mentions without commands, negation, and self-correction.

Training/validation/test splitting is grouped by whole capture session to avoid near-duplicate leakage.

## Physical classifier toolchain

Directory: `aihub/command_classifier/`.

Implemented:

- strict corpus validation;
- duplicate-byte and SHA mismatch rejection;
- exact 48,000-sample input contract;
- session-grouped train/validation/test split;
- small raw-waveform 1-D Conv/SeparableConv TensorFlow model;
- training-only gain/noise/time-shift augmentation;
- validation calibration for confidence, top-two margin, and explicit opposite-action margin;
- semantic held-out safety evaluation;
- TFLite export.

A `physical-command-qualified.tflite` artifact is emitted only if the development gate passes:

- held-out physical examples >= 3,000;
- correct physical execution >= 98%;
- wrong device = 0;
- wrong action = 0;
- false physical execution rate on `OTHER` < 0.1%.

No real classifier has been trained or qualified yet because no real Fold4 corpus is committed/provided. The runtime therefore remains intentionally reject-all.

### Runtime correction

Do **not** add standalone `onnxruntime-android` while `sherpa-onnx:v1.13.4` remains in the APK. sherpa's Android build already carries a version-pinned `libonnxruntime.so`.

The protected classifier instead uses Google Play services LiteRT:

```text
com.google.android.gms:play-services-tflite-java:16.5.0
InterpreterApi.Options().setRuntime(FROM_SYSTEM_ONLY)
```

If LiteRT/model initialization fails, physical commands remain disabled.

## Porcupine wake path

Dependency: `ai.picovoice:porcupine-android:4.0.2`.

`PorcupinePcmWakeDetector`:

- uses low-level `Porcupine.process(short[])` only;
- never uses `PorcupineManager` or another microphone owner;
- adapts AudioEngine 320-sample frames to Porcupine's exact frame length without dropping samples;
- resets/rebuilds Porcupine across PCM discontinuities;
- explicitly loads the Korean parameter model.

### Korean model provisioning

`PorcupineKoreanModelProvisioner` performs one-time setup:

1. downloads the Korean `porcupine_params_ko.pv` from a pinned Picovoice repository commit into app-private storage;
2. verifies the exact upstream Git blob identity before installing it;
3. invokes Porcupine's official `trainWakeWordFromPhrase(accessKey, ..., "ko", "옥자야")` API;
4. caches the generated Android `.ppn` in app-private storage.

Pinned upstream state:

- repository commit: `b42ec9f849c05bb2aa99e6cbd1c85c9b66e103bb`;
- Korean parameter Git blob: `3e9b62e31fe59481d52d74e45415d62eb52e23e9`;
- file: `lib/common/porcupine_params_ko.pv`.

The Picovoice AccessKey is not committed or persisted by the provisioner.

Provisioning can require network once. Wake inference after provisioning is local.

### Fold4 live smoke test

Launcher: **Okja Porcupine Wake** (`PorcupineWakeActivity`).

The screen:

- accepts the AccessKey in memory only;
- provisions/validates the Korean assets;
- starts `AudioEngine`;
- feeds only shared PCM to Porcupine;
- reports raw `옥자야` detections, engine version, and frame size.

This screen is a smoke test only. Its raw detection count is not false-wakes/hour because intentional wakes are not annotated.

## Fold4 full-ASR evidence

### Moonshine tiny-ko

Observed combined evidence:

- semantic suffix: 11/15 (73.3%);
- physical device commands: 6/10 (60%);
- typical init: ~0.6 s;
- typical replay/decode: ~0.15–0.16 s.

Critical failures include:

- `TV 켜줘 -> TV 꺼줘`;
- `에어컨 꺼줘 -> 에어컨 꺼져`;
- one unrelated output for a valid AC command.

Decision: conversation/open-language only.

### SenseVoice 2025

- suffix: 0/5;
- physical commands: 0/4;
- init: 1978.2 ms mean;
- decode: 325.0 ms mean;
- unusable CJK/mixed output.

Decision: rejected.

### Korean streaming Zipformer

- suffix: 4/10;
- physical commands: 0/6;
- one `<EMPTY>` positive;
- init: ~1344 ms;
- decode: ~433 ms.

Decision: rejected primary candidate.

## Current release gates

- normal physical-command correctness >= 98%;
- stress correctness >= 95%;
- opposite-action execution = 0 observed in >= 6,000 balanced held-out physical trials;
- false physical execution = 0 observed over >= 300 h representative household negatives;
- false wake < 0.1/hour;
- normal-condition missed wake <= 5%;
- action-token clipping = 0 observed in >= 1,000 physical-command utterances;
- no physical execution across PCM/audio-route discontinuity.

Abstention is preferable to wrong physical execution.

## Current execution order

### E1 — real five-class Fold4 command corpus

Use the **Okja Command Dataset** launcher across multiple sessions/speakers/conditions.

Immediate model-development minimum: enough complete sessions for every class to appear independently in train, validation, and test. The trainer deliberately refuses leaky/incomplete splits.

### E2 — train/calibrate candidate

Run the corpus validator and trainer in `aihub/command_classifier/`.

The Android protected path stays reject-all unless a model actually clears the encoded development safety gate.

### E3 — Porcupine Fold4 smoke + same-PCM benchmark

Use **Okja Porcupine Wake** with a Picovoice AccessKey to validate provisioning and basic `옥자야` detection on the actual Fold4.

Then move from smoke testing to annotated same-PCM wake cases and long negative listening:

- controlled positive recall;
- >= 50 h initial representative negatives;
- target false wake < 0.1/hour;
- continue toward >=300 h release evidence.

### E4 — wake-relative slicing / endpointing

Instrument wake sample position, speech onset, slice boundaries, action-token retention, and trailing silence.

Pass target:

- command-content retention >=99%;
- zero action-token clipping / >=1,000 physical utterances;
- physical endpoint p95 <=500 ms;
- zero executable slice crossing a discontinuity.

Do not replace VAD until this measurement proves the current VAD is the limiter.

### E5 — Moonshine conversation requalification

Re-test Moonshine only for conversation/open-language success and latency. Physical command correctness is no longer its authorization criterion.

### E6 — Android/Samsung/TTS hardening

Run screen-off, fold/unfold, Activity recreation, audio-route, Bluetooth, Doze, Samsung sleeping-management, and TTS self-trigger soak tests.

### E7 — production migration

Only after protected classifier, wake, endpointing, and lifecycle gates pass:

- migrate `MainActivity`;
- add the user-started microphone foreground-service lifecycle;
- remove the old `AudioRecord -> release -> SpeechRecognizer` production topology.

## Current external blockers

Repository-side scaffolding is no longer the main blocker.

Actual measured progress now requires:

1. real Fold4 physical-command recordings;
2. a Picovoice AccessKey for the Porcupine benchmark.

The AccessKey must remain outside Git. No wake or classifier performance result should be claimed until those target-device runs exist.

## Verification status

The source changes have been committed to `feat/voice-pipeline-v2`. A successful Android/JVM build for the latest head has **not yet been independently observed through the available GitHub status interface**, so compile/CI status must be treated as unverified until a workflow result is retrieved.
