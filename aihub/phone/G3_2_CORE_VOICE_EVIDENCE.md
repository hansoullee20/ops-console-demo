# G3.2 Core Voice Events — Closure Evidence

**Gate:** G3.2 Core voice events implemented  
**Branch:** `aihub-voice-test`  
**Evidence date:** 2026-08-13 KST

## Scope

G3.2 requires real producers for the core voice lifecycle:

- `wake.candidate`, `wake.detected`, `wake.rejected`
- `listening.started`, `listening.stopped`, `listening.failed`
- `transcript.partial`, `transcript.final`, `transcript.failed`
- `intent.requested`, `intent.resolved`, `intent.failed`
- `confirmation.requested`, `confirmation.accepted`, `confirmation.rejected`
- guarded command accepted/completed/failed events

This gate is an event/lifecycle contract gate. It does **not** claim that TV, AC, phone-finder or other physical adapters are integrated.

## Android recognizer lifecycle

Commit `88fd83faf4836557d65ac6e03c0d359e9f642a38` (`Make live voice lifecycle observable`) completes the recognizer-owned lifecycle on the real Android `SpeechRecognizer` path.

The live activity emits wake candidate/detected/rejected decisions, listening start/stop/failure, partial/final transcript and transcript failure events. Exact payload policy lives in `okja_core_voice_events.py`. `VoiceEventLedger` is bounded and volatile; it does not persist transcript/event contents to disk.

Clean evidence on the same commit:

- evaluator/contract run `31684855800` — success
- Android APK build run `31684855790` — success

## Intent and confirmation lifecycle

Commit `2f2f892b5a1a4f4e6515db118597f51ba08d4214` (`Complete live intent and confirmation lifecycle`) adds the missing real bridge producers.

`VoiceIntentSession` receives the actual `transcript.final` envelope before the agent request and emits exact `bridge.intent` events with volatile retention. It distinguishes ordinary assistant queries from a deliberately narrow set of current device intents: TV power on/off, AC power on/off and phone-finder ring.

Device intents require a second spoken turn. The bridge emits `confirmation.requested`, then accepts only an explicit confirm token or rejects an explicit cancel token. Unrecognized confirmation speech emits `intent.failed` while preserving the pending confirmation; expiry emits `confirmation.rejected`. Causation links the confirmation response to the original confirmation request.

Raw transcript text is not copied into structured intent/confirmation payloads.

A confirmed device request is **not** executed when no physical adapter is connected and is not reported as executed. This preserves the boundary between G3.2 lifecycle evidence and G3.15/G3.16/G3.17/G4 physical-integration gates.

Clean evidence on the same commit:

- evaluator/contract run `31692595222` — success
- Android APK build run `31692595239` — success

## Command boundary

Existing commit `f2a41f6` supplies the guarded, idempotent device-command accepted/completed/failed event boundary. Physical adapters remain separate gates.

## Verdict

The G3.2 event-production Definition of Done is satisfied by the combined live Android recognizer path, live phone bridge intent/confirmation path and existing guarded device-command boundary.

This evidence does not close any physical integration, UI, Fold4 reliability, sensor or household-pilot gate.
