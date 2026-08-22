# ADR-0001: Single microphone owner

Status: Accepted for voice-pipeline-v2

## Context

Fold4 diagnostics showed that releasing the wake gate `AudioRecord` and then starting Android `SpeechRecognizer` clips the beginning of connected utterances. A production design that changes microphone ownership between wake and command ASR therefore cannot meet the `옥자야 뭐하니` continuity requirement reliably.

## Decision

`AudioEngine` is the only component allowed to create and own `AudioRecord`.

Wake detection, VAD, ASR, and diagnostics consume PCM frames and pre-roll through interfaces. Engine integrations that require exclusive microphone ownership are not eligible for the final production path.

The ring buffer capacity and ASR pre-roll are separate configuration values. Initial defaults are 3000 ms capacity and 1500 ms pre-roll.

## Consequences

- Wake-to-ASR no longer requires microphone release/reacquisition.
- Local KWS and ASR implementations become replaceable behind PCM contracts.
- Android SpeechRecognizer remains a compatibility/fallback path rather than the architectural owner of capture.
- TTS echo/barge-in policy can be added later without changing microphone topology.
- MainActivity migration happens only after the new PCM pipeline passes device acceptance.
