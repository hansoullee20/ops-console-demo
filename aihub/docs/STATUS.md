# Project Okja — Current Status

Last updated: 2026-08-20 (Asia/Seoul)

This is the authoritative current-state source for Project Okja.

## State

**STATE: NEED INPUT — ONE UNIQUE FOLD4 TRIAL RESULT MISSING**

Repository: `hansoullee20/ops-console-demo`
Branch: `feat/voice-pipeline-v2`
Draft PR: `#20 Voice pipeline v2: single-owner PCM audio core`
Base: `aihub-voice-test`
Root-cause checkpoint: `8cc9897d6c5898c9ccd5be73599ef91c35f01659`

Latest normal CI after the semantic command-metric correction: run `#224` / `32325631666` — success.
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

1. sherpa Moonshine tiny-ko v2 remains the best current Korean local-ASR candidate from the first Fold4 batch, but its command accuracy is not yet acceptable;
2. sherpa SenseVoice Korean/Multilingual is now the next comparator because current sherpa-onnx explicitly supports Korean and Android simulated-streaming/offline deployment;
3. Korean streaming Zipformer is retained only as comparison evidence after a positive-case silent-empty failure and poor device-command preservation;
4. Porcupine low-level PCM remains the first Android-ready Korean wake baseline.

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

## Fold4 evidence — 10 unique saved runs visible in the supplied screenshots

The user reports 11 total trials, but the screenshots currently available to the assistant contain **10 unique saved PCM/JSON IDs**. One additional unique run is still required for a complete 11-run analysis.

All cases below used one captured PCM replayed unchanged to both engines.

| Saved PCM ID | Phrase | Moonshine transcript | Moon semantic suffix | Moon init/decode | Zipformer transcript | Zip semantic suffix | Zip init/decode |
|---|---|---|---:|---|---|---:|---|
| `1787193143356-0` | `옥자야 뭐하니` | `복자야 뭐하니?` | pass | 603 / 151 ms | `뭐하니?` | pass | 1266 / 422 ms |
| `1787193171113-1` | `옥자 TV 켜줘` | `복자 티비 켜줘.` | pass* | 597 / 156 ms | `<EMPTY>` | fail | 1278 / 419 ms |
| `1787193359645-2` | `옥자 에어컨 꺼줘` | `옥자 에어컨 꺼져.` | fail | 627 / 166 ms | `옥자에어컨꺼져.` | fail | 1382 / 449 ms |
| `1787193379289-0` | `옥자야 뭐하니` | `옥자야 뭐하니?` | pass | 607 / 155 ms | `뭐하니?` | pass | 1437 / 424 ms |
| `1787193396845-1` | `옥자 TV 켜줘` | `복자 티비 켜줘.` | pass* | 635 / 166 ms | `옥자.` | fail | 1400 / 440 ms |
| `1787193500111-2` | `옥자 에어컨 꺼줘` | `옥자 에어컨 꺼줘.` | pass | 663 / 166 ms | `오빠 에어컨꺼져.` | fail | 1343 / 429 ms |
| `1787193522270-0` | `옥자야 뭐하니` | `복자야 뭐하니?` | pass | 612 / 158 ms | `옥자야뭐하니?` | pass | 1380 / 456 ms |
| `1787193542544-1` | `옥자 TV 켜줘` | `옥자 티비 꺼줘.` | fail | 652 / 159 ms | `옥자티비꺼져.` | fail | 1311 / 428 ms |
| `1787193577193-2` | `옥자 에어컨 꺼줘` | `복잡해요. 큰 꺼져.` | fail | 629 / 173 ms | `옥자에어컨꺼져.` | fail | 1308 / 428 ms |
| `1787193589738-0` | `옥자야 뭐하니` | `억자야 뭐하니?` | pass | 622 / 150 ms | `옥자야? 뭐하니?` | pass | 1330 / 435 ms |

`*` The old APK displayed `suffix: false` for `TV` vs `티비`; the corrected semantic metric counts this as preserved while keeping transcript exactness separate.

### Aggregate from these 10 unique runs

Moonshine tiny-ko:

- non-empty positive output: **10/10**;
- semantic suffix preserved overall: **7/10 (70%)**;
- conversational `뭐하니` suffix: **4/4**;
- physical-device commands only (`TV 켜줘`, `에어컨 꺼줘`): **3/6 (50%)**;
- mean model init: **624.7 ms**;
- mean replay/decode: **160.0 ms**;
- exact/acceptable wake-token text (`옥자`/`옥자야`) appeared in 4/10 transcripts, but this is ASR text fidelity, not a KWS benchmark.

Korean streaming Zipformer:

- non-empty positive output: **9/10**;
- positive-case silent-empty failure: **1/10**;
- semantic suffix preserved overall: **4/10 (40%)**;
- conversational `뭐하니` suffix: **4/4**;
- physical-device commands only: **0/6 (0%)**;
- mean model init: **1343.5 ms**;
- mean replay/decode: **433.0 ms**.

Moonshine was about **2.15x faster to initialize** and **2.71x faster to decode** than Zipformer across these 10 runs.

### Review / decision

The first five-run review was too optimistic for Moonshine. With the larger visible batch, Moonshine remains clearly better than Zipformer, but **3/6 device-command preservation is not acceptable for production device control**.

Important failure modes:

- Moonshine changed `TV 켜줘` -> `TV 꺼줘` once, which is a dangerous action inversion and must remain a hard failure.
- `에어컨 꺼줘` -> `에어컨 꺼져` occurred repeatedly; this must not be normalized into success at the authorization boundary.
- One Moonshine AC run hallucinated `복잡해요. 큰 꺼져.` rather than a usable device command.
- Zipformer produced one total `<EMPTY>` positive case and failed all 6 observed physical-device command suffixes.

**ASR decision:**

- do not promote Zipformer;
- keep Moonshine as the current leading candidate, but do not integrate it as the sole production command recognizer yet;
- benchmark SenseVoice on the same saved PCM corpus before selecting the local ASR engine;
- deterministic device routing/authorization must continue to reject ambiguous or action-inverted transcripts.

Current upstream evidence for SenseVoice:

- sherpa-onnx SenseVoice supports Korean (`ko`) alongside zh/en/ja/yue;
- sherpa-onnx publishes Android simulated-streaming/VAD+ASR APK guidance for SenseVoice;
- current Kotlin API includes `OfflineSenseVoiceModelConfig` and SenseVoice model helpers.

## Next execution order

### Task C1 — locate the missing 11th unique run — NEED INPUT

The screenshots supplied so far expose 10 unique `Saved:` PCM IDs. If 11 trials were actually run, send the one screenshot whose `Saved:` ID is not listed in the table above.

### Task C2 — add SenseVoice to the identical-PCM harness — NEXT CODE TASK

- provision the official sherpa SenseVoice Korean-capable int8 model with recorded SHA-256 provenance;
- add a microphone-free `SherpaSenseVoiceBenchmarkEngine`;
- replay the same saved PCM cases through Moonshine and SenseVoice;
- keep Zipformer optional as historical/fail-fast evidence instead of decoding every new trial;
- preserve the corrected semantic-command metric and wrong-action fail-closed behavior.

### Task C3 — improve corpus collection before larger manual runs

- compact trial counter and aggregate per-phrase summary;
- export corpus-summary JSON;
- separate transcript exactness, semantic command preservation, and silent failure;
- make Moonshine/SenseVoice the default pair;
- keep Zipformer behind an optional diagnostic toggle.

### Task D — VoiceSessionController

Architecture work can continue independently, but production ASR selection remains gated by the same-PCM comparison. The controller must:

- preserve already-captured command suffixes;
- enforce one capture owner / one utterance decode path;
- reject stale callbacks and bound retries;
- make MIC_OFF/TTS transitions deterministic;
- require clean PCM integrity before physical command authorization.

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

No architecture/code blocker for continuing SenseVoice integration.

For the requested **complete 11-trial statistical analysis**, one unique trial screenshot/ID is missing from the material currently visible to the assistant.

## Documentation hierarchy

1. `STATUS.md` — current state and next actions.
2. `ARCHITECTURE.md` — intended architecture.
3. `architecture/ADR-*.md` — decision rationale.
4. `SECURITY_BACKLOG.md` — deferred security/release gates.
5. `architecture/VOICE_ENGINE_BENCHMARK_PLAN.md` — benchmark methodology.
6. Historical `AIHUB_*.md` and diagnostic notes — evidence only.
