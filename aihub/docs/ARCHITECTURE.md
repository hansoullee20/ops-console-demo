# Project Okja — Canonical Architecture

Status: current target architecture for the family prototype and next production-oriented milestones.

Revalidated: 2026-08-21 against current Fold4 evidence and the implemented voice-session core.

This document is authoritative for **what the system should become**. `STATUS.md` is authoritative for **what is actually implemented today**.

## Product principle

Project Okja should feel like one assistant even if deterministic and generative components exist internally.

The architecture optimizes for:

- predictable household-device control;
- local-first audio handling;
- low latency;
- no unnecessary system recognition cues;
- deterministic handling before generative AI;
- fail-closed physical execution;
- reproducible Fold4 benchmarks.

## Core invariant: one microphone owner

Exactly one component owns microphone capture:

`AudioEngine`

Wake-word, VAD, ASR, command recognition, and diagnostics are PCM consumers. They must not independently create their own `AudioRecord` in the production path.

Canonical capture format:

- 16 kHz;
- mono;
- signed PCM16;
- 20 ms frames / 320 samples;
- circular buffer capacity: 3000 ms initially;
- actual ASR/wake pre-roll: configurable, initially around 1500 ms.

PCM continuity is part of command integrity. Frames carry sequence/sample-position metadata and a discontinuous utterance must not authorize a physical command.

## Target voice flow

```text
Microphone
   |
   v
AudioEngine
(single AudioRecord owner)
   |
   +---------------- PcmRingBuffer ----------------+
   |                                               |
   +--> WakeDetector                               |
   +--> VAD                                        |
   +--> Diagnostics                                |
                                                   |
Wake detected                                      |
   |                                               |
   +--> readPreRoll(configured ms) <---------------+
   +--> continue live PCM from same AudioRecord
   |
   v
Recognition layer
   |
   +--> full local ASR for general language
   |
   +--> optional command-specialized verifier/classifier
        when justified by benchmark evidence
   |
   v
VoiceSessionController
   |
   v
Transcript / Command Router
   |
   +--> deterministic intent / policy / confirmation
   |          |
   |          v
   |      device-command boundary
   |          |
   |          v
   |      physical adapter
   |
   +--> AI fallback for non-device conversation
              |
              v
             TTS
```

There is no `AudioRecord -> release -> SpeechRecognizer opens microphone` handoff in the target architecture.

## Connected wake + command

Natural single-utterance speech is a product requirement:

- `옥자야 뭐하니`;
- `옥자 TV 켜줘`;
- `옥자 에어컨 꺼줘`.

When wake is detected, recognition receives buffered PCM from before the wake decision plus continuing live PCM from the same capture session.

If a completed transcript already contains a wake prefix and command suffix, routing must process that suffix directly. It must not discard the command and open a second recognizer session.

## Wake detector contract

Wake detection is pluggable and microphone-free.

Current candidate order:

1. **Porcupine low-level PCM API** as the first Android-ready benchmark baseline. Use only the low-level API; a high-level manager that owns microphone capture does not fit Okja's topology.
2. **sherpa-onnx keyword spotting** as a research candidate only after a Korean-capable model/tokenization path is demonstrated.
3. Other local PCM-fed detectors only if supported by replay and Fold4 evidence.

The first wake benchmark must compare at least `옥자` and the longer `옥자야` trigger because a short two-syllable keyword may have a higher false-activation cost.

Wake selection is based on measured false reject, false activation, latency, CPU/PSS, background-speech robustness, and TTS self-trigger behavior.

## Recognition / ASR contract

The recognition layer consumes only caller-owned PCM.

### Current on-device evidence

**Moonshine tiny-ko** remains the incumbent local full-ASR baseline.

Combined observed Fold4 evidence across the earlier 10-run corpus plus five later same-PCM runs:

- semantic suffix: 11/15;
- physical-device command suffix: 6/10;
- typical model init around 0.6 s;
- typical replay/decode around 0.15–0.16 s.

This is insufficient for production physical actuation because dangerous action substitutions have occurred.

**SenseVoice 2025** is rejected as a primary candidate after five Fold4 same-PCM trials returned 0/5 semantic suffix preservation despite explicit `language = "ko"`; the outputs were unusable CJK/mixed-script text and were slower than Moonshine.

**Korean streaming Zipformer** is rejected as a primary candidate after 0/6 physical-command preservation in the earlier Fold4 corpus and one positive `<EMPTY>` failure.

**Android SpeechRecognizer** remains compatibility/diagnostic evidence only. It is not the target continuous production path.

### Production recognition rule

No full ASR engine is allowed to authorize a physical action merely because it produced plausible text.

The next architecture decision may introduce a command-specialized acoustic classifier or second-pass verifier for constrained physical commands while retaining full ASR for general conversation. That direction is not accepted by architecture alone; it must beat the incumbent in same-PCM/Fold4 command-safety benchmarks.

Uncertain or conflicting recognition should abstain rather than execute an opposite action.

## VAD and endpointing

VAD is another PCM consumer and must never become a second capture owner.

The ring buffer and pre-roll exist specifically to preserve audio that precedes the wake decision. Endpointing must close an utterance without clipping connected wake+command speech.

Initial candidates include sherpa/Silero-style neural VAD or another Android-suitable PCM-fed VAD. Runtime choice follows measurement, not dependency preference.

## VoiceSessionController

The ASR-agnostic `VoiceSessionController` core is now implemented and unit-tested. It is not yet wired as the production `MainActivity` lifecycle owner.

Conceptual states:

```text
IDLE
  -> CAPTURING
  -> ROUTING
  -> SPEAKING
  -> FOLLOW_UP or IDLE

Any active path -> MIC_OFF / DEGRADED
```

Required and implemented core invariants:

1. one active decoder path per utterance;
2. generation tokens reject stale callbacks;
3. bounded retries and explicit degraded recovery;
4. a command suffix already captured in the wake utterance is routed as part of the same transcript;
5. TTS speaking state blocks recursive new capture;
6. MIC_OFF invalidates active work;
7. physical device execution requires clean utterance PCM integrity;
8. duplicate/stale finish callbacks cannot execute a command twice.

The production integration must preserve these invariants when the controller is connected to `AudioEngine`, wake detection, TTS, and lifecycle events.

## Deterministic intent before AI

Routing order remains:

```text
Recognition result
   |
   v
Normalize / validate
   |
   v
Deterministic intent + safety policy
   |
   +--> known device action -> authorization / confirmation -> adapter
   |
   +--> uncertain device action -> reject / ask again
   |
   +--> non-device conversation -> AI fallback
```

Generative AI is never actuator authority.

## TTS / self-trigger policy

First production implementation should remain simple:

- block wake/capture entry while Okja TTS is speaking;
- keep state ownership in `VoiceSessionController`;
- do not add full-duplex barge-in until baseline wake and command recognition are stable;
- consider AEC/playback-aware refinements later if measured behavior requires them.

## Android lifecycle

Near-always-listening behavior must eventually respect current Android microphone foreground-service and runtime-permission constraints.

Foreground-service integration is intentionally later than core recognition correctness. It must not be mixed into early ASR/wake selection in a way that obscures audio or command failures.

## Runtime optimization

Start with CPU / standard ONNX Runtime or the runtime required by the selected model.

QNN/NPU acceleration is a later optimization after correctness, command safety, continuity, lifecycle, and battery gates pass. Accelerator availability must not dictate the recognition architecture prematurely.

## Diagnostics

Keep reproducible diagnostics:

- monotonic timestamps;
- captured/replayed PCM evidence;
- sequence/sample positions;
- engine/model versions;
- model/source hashes;
- benchmark result JSON;
- CPU/PSS/latency when accuracy gates justify longer runs.

Long-term diagnostic Activities and verbose household traces belong in a debug/diagnostic build surface, not production UI.

## Security boundary

Security work remains tracked in `SECURITY_BACKLOG.md`.

Before broader deployment or sensitive actuators, the architecture must add authenticated local boundaries, explicit actuator authorization, risk tiers, release-grade provenance, and least-privilege AI/backend execution.

## Repository direction

A dedicated `project-okja` repository remains the target after the voice-pipeline milestone stabilizes. Repository extraction should not be combined with the active runtime audio rewrite.

## Related plans

- `architecture/ADR-0001-SINGLE-MICROPHONE-OWNER.md`
- `architecture/ADR-0002-MODE-F-IS-COMPATIBILITY-ONLY.md`
- `architecture/VOICE_PIPELINE_V2.md`
- `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md`
