# Project Okja / AI Hub

Project Okja is the current product direction for the Android household voice assistant work in this repository.

> **Canonical status:** [`docs/STATUS.md`](docs/STATUS.md)
>
> **Canonical architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
>
> **Security backlog:** [`docs/SECURITY_BACKLOG.md`](docs/SECURITY_BACKLOG.md)

These three documents are the source of truth for current state, architecture, and deferred security work. Older `AIHUB_*.md`, wake-word evidence, experiment notes, and historical plans remain useful evidence, but they are not authoritative for the current implementation unless referenced by the canonical documents above.

## Current development state

The active architecture work is on `feat/voice-pipeline-v2` in draft PR #20.

The current milestone establishes a **single-owner PCM audio pipeline**:

```text
Microphone
   |
   v
AudioEngine  <-- only AudioRecord owner
   |
   +--> PcmRingBuffer
   +--> WakeDetector
   +--> VAD
   +--> Streaming ASR
   +--> diagnostics
```

The old production-style path (`QuietWakeGate -> release AudioRecord -> Android SpeechRecognizer`) is retained only as historical/diagnostic code until the new PCM-fed ASR path is device-validated.

## Current priorities

1. Keep the single-owner `AudioEngine` contract stable.
2. Build a same-PCM benchmark harness.
3. Benchmark sherpa-onnx Korean streaming ASR against Android SpeechRecognizer compatibility mode.
4. Add wake detection as a PCM consumer; do not let wake/VAD/ASR open their own microphone.
5. Replace the old MainActivity wake/recognizer path only after device acceptance.

## Repository layout

- `app/` — Android application and current voice experiments.
- `phone/` — local bridge, event contracts, deterministic intent/confirmation, device-command boundary.
- `wakeword/` — wake-word research, benchmarks, datasets, and historical evidence.
- `docs/` — current canonical project documentation and ADRs.

## Documentation rule

If two documents disagree:

1. `docs/STATUS.md` wins for what is currently done / next / blocked.
2. `docs/ARCHITECTURE.md` wins for intended production architecture.
3. ADRs explain why a major architecture decision was made.
4. `docs/SECURITY_BACKLOG.md` tracks known security work that is deliberately deferred.
5. Historical `AIHUB_*.md` and evidence files are context, not active instructions.
