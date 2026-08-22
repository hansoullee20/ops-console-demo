# ADR-0003 — Staged wake detection and hybrid physical-command authorization

Status: **superseded by ADR-0004 on 2026-08-22**

Date: 2026-08-21

> Historical rationale only. Do not use this ADR's wake-candidate ordering, mandatory Stage-B cascade, or physical-authorization rule as current implementation guidance. ADR-0004 is authoritative.

## Context

Project Okja already has a single-owner PCM architecture: `AudioEngine` is the only `AudioRecord` owner and wake/VAD/ASR/diagnostic components consume supplied 16 kHz mono PCM16 frames.

Fold4 evidence has also established that unrestricted full-ASR text is not safe enough to authorize household physical actions by itself:

- Moonshine tiny-ko is the strongest observed local full-ASR baseline, but combined observed physical-command preservation is 6/10 and includes opposite-action substitutions such as `켜줘 -> 꺼줘`;
- SenseVoice 2025 and the Korean streaming Zipformer have already failed the target-device comparator;
- uncertain recognition must therefore abstain rather than guess.

## Historical decision

ADR-0003 originally proposed a staged wake cascade (`Stage A KWS -> Stage B phrase verifier`) with openWakeWord as the first prototype, Porcupine as an independent benchmark control, and a hybrid physical-command authorization rule combining ASR and command-specialized evidence.

ADR-0004 changed those decisions after additional Fold4 evidence:

- physical commands are authorized by a closed-set acoustic classifier independently of generic ASR text;
- Porcupine 4.0.2 / `옥자야` is the first wake-engine benchmark candidate;
- a Stage-B wake verifier is added only if measured false-wake/recall results justify it.

The following ADR-0003 conclusions remain valid and are carried forward by ADR-0004:

- `AudioEngine` remains the sole microphone owner;
- `옥자야` remains the primary benchmark phrase and bare `옥자` a shorter comparison form;
- false activation must be measured on long representative negative listening, not positive-only tests;
- TTS remains half-duplex for v1;
- the eventual microphone foreground service must start from Android-supported visible/explicit user intent;
- uncertain physical actions must abstain rather than guess.

## Historical false-activation protocol

Wake evaluation progresses through increasingly long negative-listening stages:

```text
10 min developer replay
  -> 1 h controlled room
  -> 24 h household smoke
  -> 100 h multi-condition negative
  -> 300+ h release-gate negative
  -> multi-household pilot
```

The release report tracks wake recall/FRR, false activations per hour, P50/P95 latency, phrase/speaker recall, TV/background and self-TTS false activations, CPU/PSS, and later battery/thermal behavior.

With zero observed false activations, the approximate 95% Poisson upper bound is about `3 / negative_hours`; therefore roughly 300 negative hours are needed before zero observed events supports an upper bound near 0.01 false activations/hour.

## Current reference

See `ADR-0004-ACOUSTIC-PHYSICAL-AUTHORITY.md` for the active architecture and implementation order.
