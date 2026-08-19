# Project Okja — Execution Plan

## Objective
Move Project Okja into a dedicated Android repository without losing the existing experimental evidence, then replace microphone handoff architecture with a single-owner PCM pipeline and benchmark production ASR choices on the Fold4.

## Execution policy
- Preserve before deleting.
- No module except `core-audio` may instantiate `AudioRecord`.
- No ASR model is considered production-ready until measured on the target device.
- Architecture-changing experiments end in an ADR or explicit rejection note.
- Main branch stays buildable.

## Phase 0 — Repository separation
Status: BLOCKED only by absence of a connected `project-okja` repository or visible Android source repository.

Actions:
1. Create/authorize `hansoullee20/project-okja` or expose the repository containing the current Android source.
2. Copy current Android source as-is; do not refactor during migration.
3. Verify clean checkout build.
4. Add repository structure and CI.
5. Copy these architecture/research/migration documents into `docs/`.
6. Tag or otherwise preserve the pre-refactor baseline.

Exit gate:
- canonical Okja repository exists;
- clean checkout builds;
- old implementation remains reproducible;
- no secrets/private recordings/model blobs are committed.

## Phase 1 — Audio Core
Deliverables:
- `AudioEngine` as sole microphone owner;
- PCM16 / 16 kHz / mono canonical format;
- configurable 3–5 s circular buffer;
- monotonic frame/timestamp metadata;
- consumer fan-out API;
- diagnostics for capture start/stop, route, underrun/overflow and microphone acquisition count;
- unit tests for ring-buffer wraparound and pre-roll extraction.

Exit gate:
- one continuous capture can run while multiple consumers receive identical ordered frames;
- no downstream module can acquire microphone directly.

## Phase 2 — Reproducible benchmark harness
Create a versioned corpus manifest and machine-readable result schema.

Candidates:
- Android SpeechRecognizer Mode F;
- viable sherpa Korean streaming models;
- viable sherpa simulated-streaming/non-streaming Korean models where latency is acceptable.

Mandatory metrics:
- full utterance preserved;
- command exact match / WER;
- wake-to-first-partial latency;
- wake-to-final latency;
- empty-transcript/error rate;
- CPU / RSS / thermal / battery;
- cold start and model size;
- runtime/model/device version metadata.

Mode F Fold4 gate for `옥자야 뭐하니`:
- 20 trials;
- >=19 complete utterances;
- zero second microphone acquisitions;
- deterministic session termination;
- no unacceptable recognition UI/cue behavior.

## Phase 3 — Wake + VAD
- Connect wake and VAD only as PCM consumers.
- Baseline Porcupine low-level frame processing.
- Benchmark sherpa KWS where Korean custom-keyword quality is viable.
- Measure false accept, false reject, noisy-room performance and latency.

## Phase 4 — Buffered live ASR
- On wake, replay configurable 1–2 s pre-roll from the same PCM timeline.
- Continue live frames without stopping `AudioRecord`.
- Validate zero clipping at wake boundary and no duplicated frames.

## Phase 5 — Intent routing
Order:
1. normalized transcript;
2. deterministic device intent/entity matching;
3. device adapter call;
4. AI fallback only for unresolved conversational requests.

## Phase 6 — Smart-home integration
- Home Assistant adapter first where practical.
- Direct-device adapters behind the same narrow interface.
- No vendor-specific code in audio/wake/ASR modules.

## Phase 7 — TTS and barge-in
- response playback;
- self-trigger suppression;
- echo/AEC policy;
- user interruption policy;
- explicit IDLE/LISTENING/PROCESSING/RESPONDING state machine.

## Phase 8 — Reliability
Test:
- screen off/lock;
- process death/restart;
- permission revocation;
- network loss;
- Bluetooth/audio-route changes;
- long-running thermal/battery behavior;
- model load failure;
- ASR empty transcript;
- service restart restrictions.

## Current blockers and automatic next action
Current GitHub inspection on 2026-08-19 shows no connected `project-okja` repository, and the connected `ops-console-demo` tree does not expose the Okja Android source. Therefore destructive migration is not safe yet.

As soon as either repository becomes accessible, execute Phase 0 immediately, then implement Phase 1 before further feature work.

## Current upstream risk
An open sherpa-onnx issue reports empty transcription from both 2024 Korean streaming Zipformer variants on Android 1.12.17. Do not make that model a hard dependency. Treat sherpa-onnx as a runtime family and select the model only after device benchmark.