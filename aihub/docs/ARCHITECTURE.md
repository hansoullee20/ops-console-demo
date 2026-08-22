# Project Okja — Canonical Architecture

Status: current production-oriented target architecture.

Revalidated: 2026-08-22 against ADR-0004, Fold4 ASR evidence, and the code-review-hardened PCM/safety core.

This document is authoritative for **what the system should become**. `STATUS.md` is authoritative for **what is actually implemented today**. ADR-0004 is authoritative when an older ADR conflicts with this document.

## Product priorities

1. command correctness;
2. prevention of wrong physical actions;
3. latency;
4. battery/resource use;
5. developer convenience.

Abstaining from an uncertain physical command is preferable to executing the wrong action.

## Core invariant: one microphone owner

Exactly one component owns microphone capture: `AudioEngine`.

Wake-word, VAD/endpointing, ASR, command classification, and diagnostics are PCM consumers. They must not independently create `AudioRecord` in the production path.

Canonical capture format:

- 16 kHz;
- mono;
- signed PCM16;
- nominal 20 ms / 320-sample frames;
- 3 s ring-buffer capacity initially.

Every capture epoch starts at sample index 0. The ring is cleared before a new microphone epoch begins. A process-wide microphone lease prevents two `AudioEngine` instances from owning capture concurrently.

## PCM provenance is an authorization input

`PcmFrame` carries sequence and absolute sample position. Pre-roll is represented as a `PcmWindow` with exact start/end sample positions, not an unlabelled byte/short array at the authorization boundary.

A physical-command utterance is untrusted if any of these occur:

- dropped, duplicated, or out-of-order live frames;
- a gap or overlap between the pre-roll end and first live frame;
- an audio-route/capture epoch change across the executable utterance;
- missing classifier input.

A later return to contiguous PCM never repairs an already-tainted utterance.

## Target voice flow

```text
Microphone
  -> AudioEngine (sole AudioRecord owner)
       |
       +-> PcmRingBuffer / PcmWindow provenance
       +-> wake detector
       +-> VAD / endpointing
       +-> diagnostics

wake accepted
  -> wake-relative pre-roll + continuing live PCM from the same capture epoch
  -> endpointed utterance
       |
       +-> closed-set acoustic physical-command authority
       |     {TV_ON, TV_OFF, AC_ON, AC_OFF, OTHER}
       |     -> calibrated abstention
       |     -> PCM integrity gate
       |     -> deterministic device executor
       |
       +-> local full ASR for conversation / transcript semantics
             -> deterministic non-actuator routing
             -> AI fallback when appropriate
             -> TTS
```

Generic ASR and generative AI are never physical actuator authority.

There is no production `AudioRecord -> release -> Android SpeechRecognizer opens microphone` handoff.

## Physical-command authority

The selected strategy is a dedicated five-class acoustic classifier:

```text
{TV_ON, TV_OFF, AC_ON, AC_OFF, OTHER}
```

It consumes the same caller-owned PCM as the rest of the voice pipeline and produces either a typed physical authorization or abstention. A transcript such as `TV 켜줘` cannot mint authorization.

Execution requires:

1. a qualified classifier artifact and calibrated thresholds;
2. a physical class, not `OTHER`;
3. clean PCM provenance for the complete executable utterance;
4. a current, non-stale `VoiceSessionController` generation;
5. deterministic execution by the device adapter.

ASR disagreement is useful diagnostic evidence but cannot override the acoustic authority in either direction.

### Classifier runtime

The app already contains sherpa-onnx for conversation-ASR experiments, whose Android package carries its own ONNX Runtime native library. The protected classifier therefore does not add a second ONNX Runtime stack.

Classifier deployment is TFLite through Google Play services LiteRT (`play-services-tflite-java:16.5.0`) with `FROM_SYSTEM_ONLY`. Failure to initialize LiteRT, load the model, verify its manifest/hash, or run inference leaves physical control disabled.

### Development qualification

A candidate is not installable unless its held-out test set has at least:

- 3,000 physical-command examples;
- 1,000 `OTHER` examples;
- 98% correct physical execution;
- zero wrong-device decisions;
- zero wrong ON/OFF decisions;
- zero false physical executions from `OTHER`.

Session-grouped splitting prevents near-duplicate session leakage. The report records speaker overlap explicitly; session-grouped evidence must not be described as unseen-speaker validation when speakers overlap.

Production qualification remains stricter, including the >=6,000 physical trial inversion gate and >=300 h household-negative protocol.

## Full ASR

Moonshine tiny-ko remains the incumbent local full-ASR baseline for conversation/open-language use.

Observed Fold4 evidence:

- semantic suffix: 11/15;
- physical-device command suffix: 6/10;
- typical init about 0.6 s;
- typical replay/decode about 0.15–0.16 s;
- observed action-critical substitutions include `켜줘 -> 꺼줘`.

Therefore Moonshine is not physical-command authority.

SenseVoice 2025 and the tested Korean streaming Zipformer are rejected active comparator engines based on target-device evidence. Their historical results remain evidence; their Android runtime code is not part of the active architecture.

Android `SpeechRecognizer` is compatibility/diagnostic evidence only.

## Wake architecture

The first benchmark candidate is **Picovoice Porcupine 4.0.2**, phrase **`옥자야`**, using the low-level caller-owned PCM API only. `PorcupineManager` is prohibited because it would create another microphone owner.

Bare **`옥자`** remains a shorter comparison/control phrase; it is not assumed safe merely because it is convenient.

Porcupine is a benchmark candidate, not production approval. It must still pass licensing/product-fit, Fold4 recall, false-wake, latency, resource, and long-negative gates.

### Optional second-stage verifier

A mandatory Stage-B phrase verifier is **not** part of the current baseline architecture. Add one only if measured single-engine wake results cannot simultaneously meet recall and false-wake requirements. This avoids paying complexity before evidence justifies it.

Historical openWakeWord experiments remain research evidence, not the active Android runtime path.

## Wake-relative slicing and endpointing

The 3 s ring buffer remains, but a fixed 1.5 s pre-roll is not a permanent product constant.

Instrument and tune:

- wake decision sample position;
- speech onset;
- pre-roll start/end positions;
- first live sample position;
- action-token retention;
- trailing silence and endpoint latency.

Pass targets before production migration:

- command-content retention >=99%;
- zero action-token clipping in >=1,000 physical-command utterances;
- physical endpoint p95 <=500 ms;
- zero executable utterances crossing a discontinuity.

Do not replace VAD merely because another VAD exists; replace it only when measurement shows endpointing is the limiter.

## VoiceSessionController

`VoiceSessionController` is the interaction authority/state machine, not the microphone owner.

Conceptual states:

```text
IDLE -> CAPTURING -> ROUTING -> SPEAKING -> FOLLOW_UP or IDLE
Any active path -> MIC_OFF / DEGRADED
```

Required invariants:

- one utterance = one decoder lifecycle;
- generation tokens reject stale callbacks;
- retries are bounded;
- wake/capture is blocked during v1 TTS;
- duplicate finish callbacks cannot execute twice;
- physical execution requires independent typed acoustic authorization;
- physical execution requires complete PCM provenance from pre-roll through live audio;
- classifier failure/missing model fails closed.

## TTS / self-trigger

V1 is deliberately half-duplex:

- block wake/capture while Okja TTS is speaking;
- measure self-TTS wake candidates explicitly;
- defer AEC, playback-aware full duplex, and barge-in until a measured product requirement justifies the added failure modes.

## Android lifecycle

Near-always-listening production operation eventually runs in a microphone foreground service with the required foreground-service type, runtime permission, and persistent user-visible notification.

Modern Android background-start restrictions mean the design must not assume arbitrary silent creation of a microphone foreground service. Start it from a documented eligible user-visible/explicit interaction path.

Samsung screen-off, sleeping/deep-sleep management, fold/unfold, Activity recreation, Bluetooth/audio-route changes, Doze, and process death require target-device soak tests before production migration.

`MainActivity` migration remains later than command, wake, endpointing, and lifecycle qualification.

## Acceptance metrics

Physical command release gates:

- normal-condition correct execution >=98%;
- stress-condition correct execution >=95%;
- opposite-action execution = 0 observed in >=6,000 balanced held-out physical trials;
- false physical execution = 0 observed over >=300 h representative household negatives;
- no physical execution across PCM/audio-route discontinuity.

Wake release direction:

- false wake <0.1/hour for the initial product gate;
- normal-condition missed wake <=5%;
- track P50/P95 wake latency, phrase/speaker breakdown, TV/background and self-TTS false activations, CPU/PSS, battery, and thermal behavior.

When zero events are observed, report the exposure duration and statistical upper bound rather than claiming the true rate is zero.

## Diagnostics and provenance

Keep reproducible evidence:

- monotonic timestamps;
- exact PCM samples or hashes where appropriate;
- frame sequence/sample positions and capture epoch;
- detector/ASR/classifier versions and model hashes;
- intentional-wake annotations;
- hard negatives and near-threshold wake candidates;
- benchmark JSON/report outputs;
- CPU/PSS/latency and later battery/thermal measurements.

Diagnostic Activities and verbose traces belong in debug/benchmark builds, not final production UI.

## Security boundary

Security work remains tracked in `SECURITY_BACKLOG.md`.

Before broader deployment or sensitive actuators, add authenticated local boundaries, explicit actuator authorization, risk tiers, release-grade model provenance, and least-privilege AI/backend execution.

## Related decisions

- `architecture/ADR-0001-SINGLE-MICROPHONE-OWNER.md`
- `architecture/ADR-0002-MODE-F-IS-COMPATIBILITY-ONLY.md`
- `architecture/ADR-0003-STAGED-WAKE-HYBRID-COMMAND.md` — superseded historical rationale
- `architecture/ADR-0004-ACOUSTIC-PHYSICAL-AUTHORITY.md` — current decision
- `architecture/VOICE_PIPELINE_V2.md`
- `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md`
