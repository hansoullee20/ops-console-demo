# Project Okja — Canonical Architecture

Status: current target architecture for the family prototype and next production-oriented milestones.

Revalidated: 2026-08-21 against Fold4 evidence, the verified voice-session core, and the staged-wake deep-research findings.

This document is authoritative for **what the system should become**. `STATUS.md` is authoritative for **what is actually implemented today**.

## Product principle

Project Okja should feel like one assistant even though wake detection, command verification, deterministic control, and generative conversation are separate internally.

Priority order:

1. command correctness;
2. prevention of wrong physical actions;
3. latency;
4. battery/resource use;
5. developer convenience.

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
- actual recognition pre-roll: configurable, initially around 1500 ms.

PCM continuity is part of command integrity. Frames carry sequence/sample-position metadata and a discontinuous utterance must not authorize a physical command.

## Target voice flow

```text
Microphone
   |
   v
AudioEngine
(single AudioRecord owner)
   |
   +-------------------- PcmRingBuffer --------------------+
   |                                                       |
   +--> Stage A wake KWS                                   |
   +--> VAD                                                |
   +--> Diagnostics                                        |
                                                            |
Stage A candidate                                            |
   |                                                        |
   v                                                        |
Stage B high-precision Okja phrase verifier                  |
   |                                                        |
   +--> optional speaker policy                             |
   |                                                        |
   v                                                        |
Directed-speech / command gate                              |
   |                                                        |
   +--> read pre-roll <-------------------------------------+
   +--> continue live PCM from same AudioRecord
   |
   v
Recognition layer
   |
   +--> full local ASR for general conversation
   |
   +--> command-specialized acoustic/verifier path
            for physical commands
   |
   v
VoiceSessionController
   |
   v
Deterministic Transcript / Command Router
   |
   +--> known physical command
   |       -> require target/action agreement
   |       -> require clean PCM integrity
   |       -> confirmation/policy when needed
   |       -> physical adapter
   |
   +--> ambiguous/conflicting physical command
   |       -> ABSTAIN / ASK AGAIN
   |
   +--> non-device conversation
           -> AI fallback
           -> TTS
```

There is no `AudioRecord -> release -> SpeechRecognizer opens microphone` handoff in the target architecture.

## Connected wake + command

Natural single-utterance speech is a product requirement:

- `옥자야 뭐하니`;
- `옥자 TV 켜줘`;
- `옥자 에어컨 꺼줘`.

When wake is detected, recognition receives buffered PCM from before the wake decision plus continuing live PCM from the same capture session.

If a completed transcript already contains a wake prefix and command suffix, routing processes that suffix directly. It does not discard the command and open a second recognizer session.

## Staged wake architecture

Wake detection is not one binary model decision.

### Stage A — high recall, cheap, always on

Stage A consumes every PCM frame and should be computationally cheap. It may be permissive because it is not final authority.

First prototype order:

1. **openWakeWord** — first open/custom Stage-A prototype and fastest path to reproducible custom experimentation;
2. **Porcupine low-level PCM** — independent Android/Korean commercial benchmark control only; use the low-level API, never the microphone-owning manager in the Okja production topology;
3. **sherpa-onnx KWS** — longer-term open runtime candidate after an Okja/Korean model/tokenization path is demonstrated.

Porcupine requires an AccessKey/vendor dependency and therefore does not automatically satisfy the final open/local product constraint even if it wins an accuracy benchmark.

### Stage B — high precision phrase verifier

Stage B runs only on Stage-A candidates and re-scores whether the audio is truly device-directed Okja speech.

It should be trained/evaluated on:

- true `옥자야` / accepted aliases;
- phonetically similar phrases;
- household speech containing `옥자` as a mention rather than a command;
- TV/news/drama/YouTube false candidates;
- Okja's own TTS playback;
- near-threshold Stage-A rejected/candidate clips.

Stage B can be more expensive because it is invoked sparsely.

### Wake phrase policy

Primary production benchmark phrase: **`옥자야`**.

Short alias/control: **`옥자`**.

`옥자` remains supported as a usability alias only if the staged verifier can control its higher confusion risk. Later aliases such as `헤이 옥자` may be added by evidence, not by default.

## Recognition / ASR architecture

### Current full-ASR evidence

**Moonshine tiny-ko** remains the incumbent local full-ASR baseline.

Combined observed Fold4 evidence:

- semantic suffix: 11/15;
- physical-device command suffix: 6/10;
- typical model init around 0.6 s;
- typical replay/decode around 0.15–0.16 s.

It is not production-approved for physical actuation because dangerous action substitutions have occurred.

**SenseVoice 2025** is rejected as a primary candidate after five Fold4 same-PCM trials returned 0/5 semantic suffix preservation despite explicit `language = "ko"`; outputs were unusable CJK/mixed-script text and were slower than Moonshine.

**Korean streaming Zipformer** is rejected as a primary candidate after 0/6 physical-command preservation in the earlier Fold4 corpus and one positive `<EMPTY>` failure.

**Android SpeechRecognizer** remains compatibility/diagnostic evidence only.

### Selected physical-command strategy

Full ASR remains useful for transcription and general conversation, but unrestricted ASR text alone is not actuator authority.

A physical command is authorized only when all required evidence agrees:

```text
ASR target/action evidence
  + command-specialized acoustic/verifier evidence
  + deterministic target/action parser
  + PCM integrity
  + policy/confirmation when required
  -> execute
```

The command-specialized component may evolve between an acoustic intent classifier, action-word verifier, constrained grammar, or small command recognizer. Its exact model is benchmark-selected, but the **agreement-or-abstain** policy is architectural.

If evidence disagrees on `켜` versus `꺼`, target identity, negation, or another action-bearing distinction, execution is blocked and Okja asks again.

This intentionally separates physical command recognition from general conversation ASR.

## VAD and endpointing

VAD consumes caller-owned PCM and never becomes a second capture owner.

The ring buffer and pre-roll preserve audio that precedes the wake decision. Endpointing must close an utterance without clipping connected wake+command speech.

Initial implementation may use sherpa/Silero-style neural VAD or another Android-suitable PCM-fed VAD. Runtime choice follows measurement.

Pre-roll is configurable rather than hard-coded as a permanent 1.5-second product constant. Tune it against wake decision latency and actual connected-command clipping evidence.

## VoiceSessionController

The ASR-agnostic `VoiceSessionController` core is implemented and unit-tested. It is not yet wired as the production `MainActivity` lifecycle owner.

Conceptual states:

```text
IDLE
  -> CAPTURING
  -> ROUTING
  -> SPEAKING
  -> FOLLOW_UP or IDLE

Any active path -> MIC_OFF / DEGRADED
```

Implemented invariants:

1. one active decoder path per utterance;
2. generation tokens reject stale callbacks;
3. bounded retries and explicit degraded recovery;
4. already-captured command suffixes are routed in the same utterance;
5. TTS speaking blocks recursive new capture;
6. MIC_OFF invalidates active work;
7. physical execution requires clean utterance PCM integrity;
8. duplicate/stale finish callbacks cannot execute twice.

## Deterministic intent before AI

```text
Recognition evidence
   |
   v
Normalize / validate
   |
   v
Deterministic intent + physical-command agreement policy
   |
   +--> agreed device action -> authorization / confirmation -> adapter
   |
   +--> uncertain/conflicting device action -> reject / ask again
   |
   +--> non-device conversation -> AI fallback
```

Generative AI is never actuator authority.

## TTS / self-trigger policy

First production implementation is deliberately half-duplex:

- block wake/capture entry while Okja TTS is speaking;
- keep state ownership in `VoiceSessionController`;
- benchmark self-TTS false candidates explicitly;
- defer full-duplex barge-in, playback-aware cancellation, and AEC until measured need justifies them.

## Android lifecycle

Near-always-listening behavior eventually runs inside a microphone foreground service with the correct foreground-service type and runtime permissions.

Modern Android does not permit the design to assume arbitrary background creation of a microphone foreground service. The listening service must be started from a visible/user-authorized flow or another documented eligible interaction path, then kept user-visible through the required foreground notification.

Foreground-service integration remains later than wake/command correctness so lifecycle complexity does not obscure recognition failures.

## Wake benchmark and release evidence

Wake selection is based on measured:

- recall / FRR;
- false activations per hour;
- P50/P95 keyword-end-to-detection latency;
- phrase and speaker breakdowns;
- TV/background false activations;
- Okja self-TTS false activations;
- CPU/PSS;
- later battery/thermal behavior.

Negative-listening progression:

```text
10 min developer replay
  -> 1 h controlled room
  -> 24 h household smoke
  -> 100 h multi-condition negative
  -> 300+ h release-gate negative
  -> multi-household pilot
```

With zero observed false activations, an approximate 95% Poisson upper bound is `~3/T`. About 300 negative hours are therefore required before zero events supports a bound near 0.01 false activations/hour.

## Physical-command acceptance

Representative command correctness target remains at least **98%**, but raw accuracy is secondary to dangerous-error control.

Release-blocking conditions:

- opposite-action physical execution: any observed case;
- false physical execution from non-command speech or a false wake: any observed case;
- execution after PCM discontinuity: any observed case;
- duplicate execution from stale callbacks: any observed case.

Abstention is acceptable and measured separately.

## Runtime optimization

Start with CPU / standard ONNX Runtime or the runtime required by the selected model.

QNN/NPU acceleration comes later after correctness, command safety, continuity, lifecycle, and battery gates pass.

## Diagnostics

Keep reproducible diagnostics:

- monotonic timestamps;
- captured/replayed PCM evidence;
- frame sequence/sample positions;
- exact detector/ASR model versions and hashes;
- intentional-wake annotations;
- candidate/near-threshold wake events;
- benchmark JSON/report outputs;
- CPU/PSS/latency and later battery/thermal measurements.

Long-term diagnostic Activities and verbose traces belong in debug/diagnostic builds, not production UI.

## Security boundary

Security work remains tracked in `SECURITY_BACKLOG.md`.

Before broader deployment or sensitive actuators, add authenticated local boundaries, explicit actuator authorization, risk tiers, release-grade provenance, and least-privilege AI/backend execution.

## Repository direction

A dedicated `project-okja` repository remains the target after the voice-pipeline milestone stabilizes. Repository extraction should not be combined with the active runtime audio rewrite.

## Related decisions and plans

- `architecture/ADR-0001-SINGLE-MICROPHONE-OWNER.md`
- `architecture/ADR-0002-MODE-F-IS-COMPATIBILITY-ONLY.md`
- `architecture/ADR-0003-STAGED-WAKE-HYBRID-COMMAND.md`
- `architecture/VOICE_PIPELINE_V2.md`
- `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md`
