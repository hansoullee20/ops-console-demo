# Project Okja Voice Pipeline v2

Status: architecture milestone in progress

## Core invariant

Exactly one component owns the microphone: `AudioEngine`.

Wake-word, VAD, ASR, and diagnostics consume canonical PCM16 frames from `PcmAudioSource`. They must never create their own `AudioRecord`.

## Canonical audio format

- 16 kHz
- mono
- signed PCM16
- 20 ms frames (320 samples)
- circular buffer capacity: 3000 ms initially
- pre-roll: configurable, default 1500 ms

At 16 kHz mono PCM16, 3 seconds of raw audio is about 96 KB, so ring capacity and actual ASR pre-roll are intentionally independent.

## Target flow

```text
Microphone
   |
   v
AudioEngine (single AudioRecord owner)
   |
   +--> PcmRingBuffer (3 s)
   |
   +--> WakeDetector
   |
   +--> VAD
   |
   +--> diagnostics

Wake detected
   |
   +--> readPreRoll(1500 ms)
   +--> live frames continue from the same AudioRecord
   |
   v
StreamingAsrEngine
   |
   v
Transcript Router
   +--> deterministic device intent / policy
   +--> AI fallback
   |
   v
TTS
```

## Current implementation milestone

The branch introduces:

- `AudioEngine`: single owner for `AudioRecord`
- `PcmRingBuffer`: configurable circular PCM buffer
- `PcmAudioSource`: consumer-facing PCM contract
- `WakeDetector`: microphone-free wake contract
- `StreamingAsrEngine`: pre-roll + live PCM ASR contract
- unit tests for ring-buffer wrap and dynamic pre-roll

No production wake engine or ASR engine is selected in this milestone.

## Engine order

1. Keep Mode F as a bounded compatibility experiment only.
2. Build a shared recorded-audio benchmark harness.
3. Benchmark sherpa-onnx Korean streaming Zipformer and Moonshine tiny-ko against Android SpeechRecognizer on identical PCM.
4. Benchmark Porcupine low-level and sherpa-onnx KWS as interchangeable wake consumers of the same PCM source.
5. Do not integrate a wake engine that owns its own microphone.

## Acceptance gates

### Audio core

- one active `AudioRecord`
- no microphone reacquisition between wake and command ASR
- 3 s buffer remains bounded
- dynamic `readPreRoll()` works across wrap
- 8 h run shows no unbounded memory growth

### Connected wake + command

For utterances such as `옥자야 뭐하니` and `옥자 TV 켜줘`:

- command suffix preserved >= 98/100 trials
- unexplained system SpeechRecognizer cues = 0 on the final local production path
- duplicate command execution = 0
- wake-to-ASR transition does not release the microphone

## Explicit non-goals for this milestone

- no new threshold tuning of `QuietWakeGate`
- no revival of rejected LiveKit v2/v3 models
- no dependency on Android SpeechRecognizer as the primary continuous ASR
- no production barge-in yet
- no QNN/NPU optimization yet
- no repository-wide rewrite in the same change

## Migration rule

`MainActivity` remains untouched until the audio core and at least one PCM-fed ASR implementation pass device acceptance. Production migration must replace microphone ownership rather than layer another recognizer on top of the current gate/rearm state machine.
