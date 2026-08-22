# ADR-0002: Mode F is a compatibility experiment, not production architecture

Status: Accepted for voice-pipeline-v2

## Decision

`RecognizerIntent.EXTRA_AUDIO_SOURCE` remains useful for one bounded Fold4 experiment because it can show whether the installed recognition service accepts externally supplied PCM without microphone reacquisition and whether connected wake+command audio survives intact.

Passing Mode F does not make Android `SpeechRecognizer` the primary Okja ASR. The production architecture remains a single-owner PCM pipeline with pluggable local engines.

## Exit criteria

Mode F is complete after the planned Fold4 compatibility run records:

- 20 connected wake+command trials
- full phrase preservation
- second microphone acquisition evidence
- audible cue count
- exported JSONL
- on-device recognition support state

After that evidence is captured, engineering effort moves to the shared PCM ASR benchmark rather than further tuning of SpeechRecognizer lifecycle behavior.
