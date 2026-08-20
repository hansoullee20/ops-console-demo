# Project Okja — Current Status

Last updated: 2026-08-20 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: WORKING — FOLD4 CORPUS REVIEW / BENCHMARK METRIC FIX**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`
Root-cause checkpoint: `8cc9897d6c5898c9ccd5be73599ef91c35f01659`

Verified normal CI before the latest metric fix: run `#213` / `32247600131` — success.
Verified model-provisioned benchmark CI: run `#5` / `32247600046` — success.
Benchmark APK SHA-256: `3faa4902253c169484c8f50517cc93637729bffe0e28eab40f0c0ee054829896`.

Latest benchmark-metric commits:

- `f17a3e72ca642911dec1962513dbc46a3e11e7d5` — semantic command suffix normalization;
- `e1b3b348be4e8a909ae9d96a0031dc6c4ea9af49` — regression tests for command equivalence / wrong-verb rejection.

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

1. sherpa Moonshine tiny-ko v2 as the primary Korean local-ASR candidate;
2. Korean streaming Zipformer only as a fail-fast comparison because of upstream Android empty-output reports;
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

### Command-suffix metric correction

Fold4 evidence exposed a benchmark bug: expected `TV 켜줘` and recognized `티비 켜줘` were counted as suffix failure even though the device command was preserved.

The benchmark now keeps **transcript fidelity** and **command continuity** separate:

- transcript exactness remains lexical/conservative;
- command suffix scoring ignores punctuation/spacing and recognizes a deliberately tiny device-domain alias set (`TV`, `티비`, `티브이`, `텔레비전`);
- different verbs remain different (`꺼줘` does not equal `꺼져`).

Regression tests explicitly cover both the TV alias success and AC wrong-verb failure.

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

Post-task review caught/fixed Kotlin compile errors, cold model-init timing contamination, AGP asset-compression heap exhaustion, and the command-alias scoring bug above.

## Fold4 evidence

All cases below used one captured PCM replayed unchanged to both engines.

### Trial 1 — `옥자야 뭐하니`

Moonshine tiny-ko:

- transcript: `복자야 뭐하니?`
- suffix: `true`
- silent failure: `false`
- init: `603 ms`
- replay/decode: `151 ms`

Zipformer:

- transcript: `뭐하니?`
- suffix: `true`
- silent failure: `false`
- init: `1266 ms`
- replay/decode: `422 ms`

Evidence: `1787193143356-0.pcm16le`, `1787193143356-0.json`.

### Trial 2 — `옥자 TV 켜줘`

Moonshine tiny-ko:

- transcript: `복자 티비 켜줘.`
- legacy APK displayed suffix: `false`; corrected semantic command score: **preserved**
- silent failure: `false`
- init: `597 ms`
- replay/decode: `156 ms`

Zipformer:

- transcript: `<EMPTY>`
- suffix: `false`
- silent failure: `true`
- init: `1278 ms`
- replay/decode: `419 ms`

Evidence: `1787193171113-1.pcm16le`, `1787193171113-1.json`.

This reproduces the upstream-style positive-case silent-empty failure on the Fold4.

### Trial 3 — `옥자 에어컨 꺼줘`

Moonshine tiny-ko:

- transcript: `옥자 에어컨 꺼져.`
- suffix: `false`
- silent failure: `false`
- init: `627 ms`
- replay/decode: `166 ms`

Zipformer:

- transcript: `옥자에어컨꺼져.`
- suffix: `false`
- silent failure: `false`
- init: `1382 ms`
- replay/decode: `449 ms`

Evidence: `1787193359645-2.pcm16le`, `1787193359645-2.json`.

Both engines changed the actionable verb `꺼줘` -> `꺼져`; this remains a real command-recognition failure and is intentionally **not** normalized away.

### Trial 4 — repeated `옥자야 뭐하니`

Moonshine tiny-ko:

- transcript: `옥자야 뭐하니?`
- suffix: `true`
- silent failure: `false`
- init: `607 ms`
- replay/decode: `155 ms`

Zipformer:

- transcript: `뭐하니?`
- suffix: `true`
- silent failure: `false`
- init: `1437 ms`
- replay/decode: `424 ms`

Evidence: `1787193379289-0.pcm16le`, `1787193379289-0.json`.

### Trial 5 — repeated `옥자 TV 켜줘`

Moonshine tiny-ko:

- transcript: `복자 티비 켜줘.`
- legacy APK displayed suffix: `false`; corrected semantic command score: **preserved**
- silent failure: `false`
- init: `635 ms`
- replay/decode: `166 ms`

Zipformer:

- transcript: `옥자.`
- suffix: `false`
- silent failure: `false`
- init: `1400 ms`
- replay/decode: `440 ms`

Evidence: `1787193396845-1.pcm16le`, `1787193396845-1.json`.

## Current evidence review

The current Fold4 evidence is enough to change engineering priority, but not enough to claim final production accuracy.

### Moonshine

- consistently produces non-empty Korean output in the recorded positive cases;
- preserves `뭐하니` in both observed conversational repetitions;
- preserves the TV-on command semantically in both observed TV trials (`TV` -> `티비`);
- is materially faster than Zipformer in the observed cold-init and decode measurements;
- still has an important AC command error (`꺼줘` -> `꺼져`) that must be measured across repeated speakers/conditions rather than normalized away;
- wake token recognition itself is inconsistent (`옥자`/`옥자야` sometimes becomes `복자`), reinforcing that wake detection should be handled by a dedicated KWS engine rather than relying on full-transcript ASR to identify the wake token.

### Zipformer

- reproduced a positive-case silent-empty failure on Trial 2;
- omitted the wake prefix on conversational trials;
- returned only `옥자` on one TV trial;
- was roughly 2–3x slower than Moonshine in the observed decode/init measurements.

**Decision:** stop treating Korean streaming Zipformer as a primary candidate. Retain it only as recorded comparison evidence unless a future upstream fix materially changes the Android result.

## Next execution order

### Task C1 — finish metric fix CI / review — ACTIVE

- verify JVM tests and APK build on the semantic command-normalization change;
- inspect the diff after CI;
- do not ship a new large model APK merely to change the displayed suffix flag unless further manual testing requires it.

### Task C2 — improve corpus collection before more manual trials

Reduce user effort before asking for dozens of repetitions:

- add a compact trial counter and aggregate per-phrase result summary;
- make Moonshine the default measured engine;
- keep Zipformer optional/fail-fast rather than decoding every case;
- export a small corpus summary JSON in addition to per-trial JSON;
- include semantic command score separately from transcript exactness.

### Task D — VoiceSessionController

Begin once the metric fix is green and the Moonshine path remains the primary candidate:

- move voice lifecycle authority out of `MainActivity`;
- preserve already-captured command suffixes;
- enforce one capture owner / one utterance decode path;
- reject stale callbacks and bound retries;
- make MIC_OFF/TTS transitions deterministic;
- require clean PCM integrity before physical command authorization.

The controller may initially target Moonshine as the local ASR implementation behind the interface; engine choice remains replaceable.

### Task E — wake benchmark

1. Porcupine low-level Korean/custom wake baseline.
2. sherpa KWS only if Korean support/model evidence is established.

Wake correctness is evaluated independently from whether ASR transcribes `옥자` correctly.

### Task F — production migration

After ASR/wake acceptance:

- migrate `MainActivity` to `AudioEngine` + `VoiceSessionController`;
- remove old Gate -> release -> `SpeechRecognizer` production topology;
- add current-Android microphone foreground-service lifecycle through a visible/user-authorized start flow;
- separate diagnostic and release build surfaces.

Later release gates remain tracked separately: dedicated repo extraction (#22), deferred security work (#21), and legacy-doc archive (#25).

## Current blocker

No architecture blocker and no immediate user-input blocker.

The current work is code-side: complete CI/review of the metric correction, then improve the benchmark collection flow before requesting a larger Fold4 corpus.

## Documentation hierarchy

1. `STATUS.md` — current state and next actions.
2. `ARCHITECTURE.md` — intended architecture.
3. `architecture/ADR-*.md` — decision rationale.
4. `SECURITY_BACKLOG.md` — deferred security/release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology.
6. Historical `AIHUB_*.md` and diagnostic notes — evidence only.
