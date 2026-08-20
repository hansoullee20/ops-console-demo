# Project Okja — Current Status

Last updated: 2026-08-20 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: NEED INPUT — SECOND FOLD4 SAME-PCM ASR TRIAL**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`
Root-cause checkpoint: `8cc9897d6c5898c9ccd5be73599ef91c35f01659`

Verified normal CI: run `#213` / `32247600131` — success.
Verified model-provisioned benchmark CI: run `#5` / `32247600046` — success.
Benchmark APK SHA-256: `3faa4902253c169484c8f50517cc93637729bffe0e28eab40f0c0ee054829896`.

## Current architecture

- `AudioEngine` is the sole production `AudioRecord` owner.
- Canonical audio: 16 kHz, mono, PCM16, 20 ms frames.
- Wake/VAD/ASR/diagnostics consume shared PCM and must not acquire the microphone independently.
- `PcmRingBuffer` supplies pre-roll without microphone handoff.
- `PcmFrame` carries monotonic sequence/sample-position metadata.
- `PcmContinuityTracker` and `UtteranceAudioIntegrityGate` detect/fail closed on PCM loss.
- Deterministic device routing stays ahead of generative AI.
- Android `SpeechRecognizer` / Mode F remains compatibility evidence, not the continuous production path.

## 2026-08 source revalidation

The execution order was rechecked against current Android platform documentation and maintained sherpa-onnx / Picovoice sources.

Current benchmark priority:

1. sherpa Moonshine tiny-ko v2 as first primary Korean local-ASR candidate;
2. Korean streaming Zipformer as a short fail-fast comparison because of upstream Android empty-output reports;
3. Porcupine low-level PCM as the first Android-ready Korean wake baseline;
4. sherpa KWS only after Korean model/tokenization support is demonstrated.

## Completed / reviewed engineering work

### PCM and benchmark core

- single-owner `AudioEngine`;
- 3 s ring buffer / configurable pre-roll;
- PCM sequence and absolute sample-position metadata;
- continuity tracking and utterance integrity gate;
- same-PCM `AsrBenchmarkHarness`;
- exact transcript / command-suffix / silent-empty checks;
- monotonic replay timing regression test;
- bounded utterance buffer that fails rather than silently truncating.

Review previously caught and fixed an absolute-clock latency bug.

### Korean local ASR adapters

`SherpaMoonshineBenchmarkEngine`:

- current Korean Moonshine tiny-ko model;
- supplied PCM only, no microphone ownership;
- bounded utterance decode;
- final-only first benchmark adapter.

`SherpaStreamingAsrEngine`:

- sherpa-onnx Android runtime pinned to `v1.13.4`;
- official Korean streaming Zipformer configuration;
- supplied PCM only, no microphone ownership.

### Fold4 benchmark surface

`LocalAsrBenchmarkActivity`:

- captures one four-second PCM case through `AudioEngine`;
- checks capture continuity;
- stops capture before recognizers are instantiated;
- saves raw PCM16;
- replays the identical PCM to Moonshine and Zipformer;
- reports transcript, command-suffix preservation, silent-empty result, model-init time, replay/decode time;
- saves JSON evidence.

Post-task review caught/fixed Kotlin compile errors, cold model-init timing contamination, and AGP asset-compression heap exhaustion. `.onnx` / `.ort` model assets are now packaged uncompressed.

## Fold4 evidence

### Trial 1 — 2026-08-20 — `옥자야 뭐하니`

Target: Galaxy Z Fold4.
One recorded PCM case was replayed unchanged to both engines.

Moonshine tiny-ko:

- transcript: `복자야 뭐하니?`
- command suffix preserved: `true`
- silent failure: `false`
- model init: `603 ms`
- replay/decode: `151 ms`

Korean streaming Zipformer smoke:

- transcript: `뭐하니?`
- command suffix preserved: `true`
- silent failure: `false`
- model init: `1266 ms`
- replay/decode: `422 ms`

Saved device evidence shown by benchmark UI:

- `1787193143356-0.pcm16le`
- `1787193143356-0.json`

Review of Trial 1:

- Same-PCM path is functioning on Fold4.
- Both engines preserved the conversational/command suffix `뭐하니`.
- Moonshine was faster in both cold init and decode for this one case.
- Neither engine exactly recognized the wake prefix: Moonshine changed `옥자야` to `복자야`; Zipformer omitted it entirely.
- Zipformer did **not** reproduce a total silent-empty output on this trial, so the upstream issue is not assumed universal on this Fold4/runtime combination.
- One trial is insufficient for accuracy or production-readiness claims.

## Next execution order

### Task B2 — second Fold4 same-PCM trial — NEXT

Run exactly one case:

`옥자 TV 켜줘`

Record the same displayed fields for both engines. The key question is whether the actionable command suffix `TV 켜줘` survives even if the wake token is misrecognized or omitted.

### Task C — expand same-PCM corpus

After review of the second trial, continue one hardware test at a time with:

- `옥자 에어컨 꺼줘`;
- repeated connected utterances;
- quieter speech;
- TV/background negatives.

Only then calculate exact accuracy / WER-CER and collect CPU/PSS/thermal/battery evidence.

### Task D — VoiceSessionController

After at least one PCM-fed local ASR demonstrates acceptable command continuity:

- move voice lifecycle authority out of `MainActivity`;
- preserve already-captured command suffixes;
- enforce one capture owner / one utterance decode path;
- reject stale callbacks and bound retries;
- make MIC_OFF/TTS transitions deterministic;
- require clean PCM integrity before physical command authorization.

### Task E — wake benchmark

1. Porcupine low-level Korean/custom wake baseline.
2. sherpa KWS only if Korean support/model evidence is established.

### Task F — production migration

After ASR/wake acceptance:

- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove old Gate -> release -> `SpeechRecognizer` production topology;
- add current-Android microphone foreground-service lifecycle through a visible/user-authorized start flow;
- separate diagnostic and release build surfaces.

Later release gates remain tracked separately: dedicated repo extraction (#22), deferred security work (#21), and legacy-doc archive (#25).

## Current blocker

No code/architecture blocker.

The next evidence gate is one physical Fold4 trial of `옥자 TV 켜줘`. Do not claim model accuracy, CPU/battery, or production readiness before the repeated device corpus exists.

## Documentation hierarchy

1. `STATUS.md` — current state and next actions.
2. `ARCHITECTURE.md` — intended architecture.
3. `architecture/ADR-*.md` — decision rationale.
4. `SECURITY_BACKLOG.md` — deferred security/release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology.
6. Historical `AIHUB_*.md` and diagnostic notes — evidence only.