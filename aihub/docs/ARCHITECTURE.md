# Project Okja — Canonical Architecture

Status: current target architecture for the family prototype and next production-oriented milestones.

Revalidated: 2026-08-19 against current Android platform documentation and actively maintained sherpa-onnx / Picovoice upstream documentation.

This document is authoritative for **what the system should become**. `STATUS.md` is authoritative for **what is actually implemented today**.

## Product principle

Project Okja should feel like **one assistant** even if several deterministic components exist internally.

The architecture should optimize for:

- simple hands-free use;
- elderly/senior usability;
- predictable device control;
- local-first audio handling;
- low latency;
- minimal unexplained system sounds;
- deterministic handling before generative AI;
- clean failure modes;
- reproducible device tests.

## Core invariant: one microphone owner

Exactly one component owns the microphone:

`AudioEngine`

Wake-word, VAD, ASR, and diagnostics are PCM consumers. They must not independently create their own `AudioRecord` in the production path.

Canonical capture format:

- 16 kHz;
- mono;
- signed PCM16;
- 20 ms frames (320 samples);
- circular buffer capacity: 3000 ms initially;
- actual ASR pre-roll: configurable, initially 1500 ms.

Capacity and pre-roll are intentionally independent. At this format, several seconds of raw PCM are inexpensive in memory.

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
Local PCM-fed ASR
   |
   v
Transcript Router
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

When wake is detected, ASR receives buffered PCM from before the wake decision plus continuing live PCM from the same capture session.

The command suffix must not be discarded simply because the wake phrase was detected in the same utterance.

If the transcript is already `옥자야 TV 켜줘`, routing should normalize/strip the wake prefix and process `TV 켜줘` without launching another microphone/recognizer session.

## Wake detector contract

Wake detection is pluggable.

Current candidate order:

1. Porcupine low-level PCM API as the Android-ready baseline. Use the low-level API only; the high-level Manager owns microphone capture and therefore does not fit Okja's topology.
2. sherpa-onnx keyword spotting as a research candidate only after a Korean-capable model/tokenization path is demonstrated. Current documented pretrained KWS models/APKs are Chinese/English, so Korean readiness must not be assumed.
3. Other local PCM-fed detectors only if proven by the same replay/device benchmark.

Rules:

- the wake engine does not own the microphone;
- the wake engine consumes canonical PCM frames;
- model/runtime selection is based on measured false reject / false activation / CPU / battery behavior;
- rejected historical models remain evidence, not default production candidates.

## ASR contract

Primary architecture direction: local PCM-fed Korean ASR behind the Okja ASR contract.

Current benchmark order after the 2026-08 upstream recheck:

1. **sherpa-onnx Moonshine tiny-ko v2** — first primary local Korean benchmark. The initial Okja adapter is bounded utterance-scoped/offline decode and therefore does not pretend to expose native partial streaming; sherpa's official Android path combines Moonshine with VAD for real-time/simulated-streaming use.
2. **sherpa Korean streaming Zipformer** — short fail-fast smoke before any long benchmark. Upstream issue `k2-fsa/sherpa-onnx#2886` remains open and reports silent empty transcription from the Korean streaming models on Android. A clean Fold4/v1.13.4 smoke can clear that concern for our environment; an empty positive result removes this model from the primary path.
3. **Android SpeechRecognizer Mode F** — compatibility comparison/fallback experiment only.
4. **SenseVoice** — optional later local fallback if the dedicated Korean candidates are unsuitable.

Android SpeechRecognizer is not the target continuous production ASR. Current Android documentation still says the API is not intended for continuous recognition, and `EXTRA_AUDIO_SOURCE` is implementation-dependent: an implementation that does not support it may open its own microphone.

No engine is selected for production by compile success alone. Fold4 corpus results decide the engine.

## VAD

VAD is another PCM consumer. A sherpa/Silero-based VAD is a natural candidate if it reduces runtime/dependency complexity.

VAD must not become a second capture owner.

For Moonshine, VAD can provide the utterance boundary while the model performs bounded offline decode; this is compatible with the one-microphone architecture because both consume the same PCM bus.

## Voice session state

Voice lifecycle authority should move out of `MainActivity` into a dedicated `VoiceSessionController`.

The exact implementation may evolve, but the minimal conceptual states are:

```text
IDLE
  -> CAPTURING
  -> ROUTING
  -> SPEAKING
  -> FOLLOW_UP or IDLE

Any state -> MIC_OFF / DEGRADED
```

Required invariants:

1. Only one active microphone capture owner.
2. A voice session has at most one active ASR decoding path for the same utterance.
3. Stale callbacks from an old generation cannot change current state.
4. A command suffix already captured in the wake utterance is never discarded.
5. Retries are bounded.
6. TTS does not recursively trigger wake/command execution.
7. MIC_OFF actually stops capture/inference.
8. Device execution never depends solely on free-form LLM output.
9. PCM-discontinuous utterances fail closed for physical-device authorization.

## Deterministic intent before AI

Request routing order:

```text
Transcript
   |
   v
Normalize
   |
   v
Deterministic intent / policy
   |
   +--> known safe device action -> confirmation/policy -> adapter
   |
   +--> unknown conversational request -> AI fallback
```

Existing exact command schemas, parameter bounds, negation handling, idempotency, and correlation-local confirmation are valuable and should be preserved or strengthened.

## AI backend boundary

The family prototype may continue to use local development bridges for experimentation.

Long-term production rule:

- generative AI is a conversational fallback, not the actuator authority;
- household device adapters are not exposed directly to the model;
- production AI integration should not require broad shell/filesystem/coding-agent privileges;
- cloud requests should receive only the minimum transcript/context required for the turn.

## TTS / self-trigger policy

Initial production behavior should be simple:

- keep the audio architecture controlled by the same voice controller;
- suspend or suppress wake execution while Okja TTS is speaking;
- add barge-in only after baseline wake/ASR reliability is proven;
- AEC/echo handling is an optimization milestone, not a prerequisite for the first stable pipeline.

## Android lifecycle

Always-listening behavior must eventually respect Android foreground-service and microphone permission constraints.

The architecture should support a microphone foreground service, but this should be added after the core PCM pipeline and device benchmarks are stable rather than mixed into the first ASR integration.

## Runtime optimization

Start with CPU / standard ONNX Runtime. QNN/NPU is a later optimization after the chosen Korean ASR and wake path pass accuracy, continuity, lifecycle, and battery gates. Accelerator support changes quickly and must not determine the first architecture.

## Diagnostics

Diagnostics are first-class but not production UI.

Keep:

- monotonic timestamps;
- PCM/replay evidence;
- recording/playback configuration monitoring where useful;
- model/engine version identifiers;
- model/source hashes and benchmark provenance;
- exported benchmark evidence.

Move long-term diagnostics into a debug/diagnostic build boundary so production does not ship experimental Activities or verbose household traces.

## Security boundary

Security work is tracked separately in `SECURITY_BACKLOG.md` so it does not disappear while the family prototype prioritizes functionality.

Before broader deployment or sensitive actuators, the architecture must add:

- authenticated local IPC/peer identity;
- actuator-boundary authorization;
- command risk tiers;
- production/diagnostic build separation;
- least-privilege AI/backend execution;
- pinned/reviewed native runtime and model provenance for release artifacts.

## Repository direction

Project Okja has grown beyond a small sub-feature of `ops-console-demo`.

Target repository direction remains a dedicated `project-okja` repository, preserving useful Git history. Extraction should happen as a controlled migration after the current voice-pipeline milestone is stable; it should not be combined with the runtime audio rewrite in one giant change.

## Related ADRs / detailed plans

- `architecture/ADR-0001-SINGLE-MICROPHONE-OWNER.md`
- `architecture/ADR-0002-MODE-F-IS-COMPATIBILITY-ONLY.md`
- `architecture/VOICE_PIPELINE_V2.md`
- `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md`
