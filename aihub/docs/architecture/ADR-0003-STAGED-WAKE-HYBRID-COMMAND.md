# ADR-0003 — Staged wake detection and hybrid physical-command authorization

Status: accepted for implementation

Date: 2026-08-21

## Context

Project Okja already has a single-owner PCM architecture: `AudioEngine` is the only `AudioRecord` owner and wake/VAD/ASR/diagnostic components consume supplied 16 kHz mono PCM16 frames.

Fold4 evidence has also established that unrestricted full-ASR text is not safe enough to authorize household physical actions by itself:

- Moonshine tiny-ko is the strongest observed local full-ASR baseline, but combined observed physical-command preservation is 6/10 and includes opposite-action substitutions such as `켜줘 -> 꺼줘`;
- SenseVoice 2025 and the Korean streaming Zipformer have been rejected as primary candidates on the current device evidence;
- uncertain recognition must therefore abstain rather than guess.

Deep-research review of production wake systems also favors a cascade rather than one wake model being solely responsible for final activation. The research recommends a cheap high-recall first stage, a higher-precision phrase verifier, optional speaker policy, and a directed-speech/command gate. It also recommends long-duration false-activation measurement rather than relying on short positive-only tests.

## Decision

### 1. Wake is a staged decision

The target wake path is:

```text
AudioEngine PCM
  -> Stage A: always-on high-recall KWS
  -> Stage B: high-precision Okja-phrase verifier
  -> optional speaker policy
  -> directed-speech / command gate
  -> recognition
```

Stage A is intentionally allowed to be permissive. It is not final actuator authority.

The first open implementation prototype will be **openWakeWord** because it supports custom model experimentation and verifier-style second-stage work without changing microphone ownership. **Porcupine low-level PCM** remains an independent Android/Korean commercial benchmark control because its Android API supports custom audio pipelines and Korean custom wake words, but its AccessKey/vendor dependency means it is not the default final architecture. sherpa-onnx KWS remains a longer-term open runtime candidate when an Okja/Korean model path is demonstrated.

### 2. `옥자야` is the primary production benchmark phrase

`옥자` remains an accepted alias, but the shorter two-syllable form receives stronger second-stage scrutiny because short trigger phrases are expected to be more confusable in household speech.

Initial wake benchmark phrases:

- primary: `옥자야`;
- alias/control: `옥자`;
- later aliases: `헤이 옥자`, `오케이 옥자`, English variants if product requirements justify them.

### 3. Physical commands use hybrid authorization

General conversation continues through full local ASR.

Physical-device commands use an additional constrained recognition/verification path. The exact model may be an acoustic command classifier, action-word verifier, constrained grammar, or another small command-specialized recognizer, but the authorization rule is fixed:

```text
full ASR result
    +
command-specialized evidence
    +
PCM integrity
    +
deterministic target/action policy
    -> execute only if consistent
```

If the evidence disagrees on target or action, the result is `ABSTAIN / ASK AGAIN`, never a guessed physical action.

This means Moonshine may remain the conversational/transcript baseline even if a different component ultimately authorizes physical commands.

### 4. False activation is measured statistically

Wake evaluation progresses through increasingly long negative-listening stages:

```text
10 min developer replay
  -> 1 h controlled room
  -> 24 h household smoke
  -> 100 h multi-condition negative
  -> 300+ h release-gate negative
  -> multi-household pilot
```

The release report tracks at least:

- wake recall / FRR;
- false activations per hour;
- P50/P95 wake latency;
- phrase-specific and speaker-specific recall;
- TV/background false activations;
- self-TTS false activations;
- CPU/PSS and later battery/thermal behavior.

With zero observed false activations, the approximate 95% Poisson upper bound is about `3 / negative_hours`; therefore roughly 300 negative hours are needed before zero observed events supports an upper bound near 0.01 false activations/hour.

### 5. TTS remains half-duplex for the first production implementation

`VoiceSessionController` blocks new wake/capture entry while Okja TTS is speaking. Full-duplex barge-in, playback-aware cancellation, and AEC are deferred until wake and command correctness are stable and a measured product need justifies the complexity.

### 6. Android microphone service starts from visible user intent

The eventual near-always-listening microphone foreground service must be started while the app is visible or from another Android-supported explicit user interaction path. The production design must not assume it can silently create a microphone foreground service from an arbitrary background state on modern Android.

## Consequences

Positive:

- wake false-positive control no longer depends on one threshold/model;
- the final product can remain open/local even if Porcupine is used as a benchmark control;
- dangerous ASR action inversions cannot directly authorize devices;
- the same benchmark infrastructure remains useful across detector implementations;
- MainActivity migration stays blocked until wake and command-safety gates are credible.

Costs:

- an additional Stage-B wake verifier and command-specialized recognizer must eventually be implemented and measured;
- the benchmark suite must include long negative audio and explicit annotations;
- physical command latency may increase slightly because correctness and abstention are prioritized over minimum latency.

## Implementation order

1. deterministic same-PCM wake benchmark harness and annotations;
2. openWakeWord Stage-A prototype;
3. Porcupine low-level PCM benchmark control;
4. Stage-B phrase verifier using candidate clips produced by Stage A;
5. constrained physical-command verifier/classifier benchmark against Moonshine;
6. end-to-end `AudioEngine -> wake -> pre-roll/live PCM -> recognition -> VoiceSessionController` integration;
7. `MainActivity` migration and Android microphone foreground-service lifecycle;
8. long-duration household soak and release gating.

## Non-decisions

- openWakeWord is not yet declared the final wake engine;
- Moonshine is not production-approved for physical device execution;
- Porcupine benchmark success would not by itself override the open/local product constraint;
- no speaker-verification policy is mandatory for ordinary household use yet;
- no full-duplex TTS/wake behavior is required for the first production implementation.
