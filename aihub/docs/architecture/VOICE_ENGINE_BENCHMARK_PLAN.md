# Okja Voice Engine Benchmark Plan

Revalidated: 2026-08-21 against Fold4 ASR evidence, the verified `VoiceSessionController`, the existing v4 household benchmark stack, and the staged-wake research decision in ADR-0003.

All compared engines must receive the same recorded PCM whenever possible. Microphone behavior and Android lifecycle are benchmarked separately on-device.

## Architecture decision

The production direction is one `AudioEngine` microphone owner with all wake/VAD/ASR/command-recognition components consuming supplied PCM.

Android `SpeechRecognizer` remains compatibility/diagnostic evidence only.

Wake is evaluated as a staged system rather than as one perfect detector:

```text
Stage A high-recall KWS
  -> Stage B phrase verifier
  -> directed-speech / command gate
  -> recognition
```

Physical device control is also staged: full ASR can provide transcript evidence, but a physical action requires command-specialized evidence plus deterministic target/action validation and clean PCM integrity.

## Current full-ASR candidate status

### 1. sherpa-onnx Moonshine tiny-ko — incumbent full-ASR baseline

Model: `sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27`

Earlier 10-run Fold4 corpus:

- semantic suffix: **7/10**;
- conversational `뭐하니`: **4/4**;
- physical device commands: **3/6**;
- mean init: **~625 ms**;
- mean replay/decode: **~160 ms**.

Five later same-PCM runs:

- semantic suffix: **4/5**;
- physical device commands: **3/4**;
- mean init: **616.8 ms**;
- mean replay/decode: **155.2 ms**.

Combined observed evidence:

- semantic suffix: **11/15 (73.3%)**;
- physical device commands: **6/10 (60%)**.

Decision: retain as the conversational/full-ASR baseline. Do not authorize physical actions from Moonshine text alone.

### 2. sherpa-onnx SenseVoice 2025 — rejected primary candidate

Model: `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09`

Okja adapter:

- explicit `language = "ko"`;
- inverse text normalization disabled;
- caller-owned PCM only.

Five Fold4 same-PCM trials:

- semantic suffix: **0/5**;
- physical commands: **0/4**;
- mean init: **1978.2 ms**;
- mean replay/decode: **325.0 ms**;
- returned unusable CJK/mixed-script output rather than empty output.

Decision: stop manual SenseVoice collection. Historical/debug use only unless upstream behavior changes materially.

### 3. Korean streaming Zipformer — rejected primary candidate

Model: `sherpa-onnx-streaming-zipformer-korean-2024-06-16`

Observed Fold4 evidence:

- semantic suffix: **4/10**;
- physical commands: **0/6**;
- positive `<EMPTY>` failure: **1/10**;
- mean init: **~1344 ms**;
- mean replay/decode: **~433 ms**.

Decision: historical/fail-fast evidence only.

## Physical-command strategy benchmark

The next command-safety benchmark compares the incumbent Moonshine transcript path with a constrained command-specialized path.

Candidate implementations may include:

- acoustic intent classifier for a bounded device/action vocabulary;
- second-pass action-word verifier;
- constrained command grammar;
- confidence/ambiguity abstention;
- joint scoring between ASR and deterministic command candidates.

The final model form is not predetermined. The authorization behavior is predetermined:

```text
ASR target/action
  + specialized command evidence
  + deterministic parser/policy
  + PCM integrity
  -> execute only if consistent
```

Disagreement on target/action/negation => **ABSTAIN / ASK AGAIN**.

Generic WER is secondary. The primary metrics are:

- correct physical execution;
- wrong-opposite-action execution;
- wrong-target execution;
- false physical execution;
- abstention rate;
- command latency.

## Recognition corpus

Core fail-fast connected utterances:

1. `옥자야 뭐하니`
2. `옥자 TV 켜줘`
3. `옥자 에어컨 꺼줘`

The three-phrase set is not a production acceptance corpus.

The larger command-safety corpus must include:

- `켜` / `꺼`;
- `켜줘` / `꺼줘`;
- `꺼줘` / `꺼져`;
- negated commands;
- target substitutions;
- wake-only speech;
- device words used conversationally without commands;
- TV/AC wording variants;
- quiet and elderly-soft speech;
- background TV/news/drama speech.

## Command scoring rules

Transcript fidelity and device-command preservation remain separate metrics.

Tiny allowed target aliases:

- `TV`;
- `티비`;
- `티브이`;
- `텔레비전`.

Punctuation/spacing differences do not by themselves fail semantic command scoring.

Action changes are hard failures and are never normalized away:

- `켜줘` -> `꺼줘`;
- `꺼줘` -> `꺼져`.

Benchmark normalization is not authorization logic.

## Canonical wake benchmark stack

Do not create a second release benchmark format. The branch already contains the canonical long-duration stack:

- `aihub/wakeword/AIHUB_V4_HOUSEHOLD_BENCHMARK_SPEC.md` — measurement protocol;
- `aihub/wakeword/v4_benchmark_schema.json` — canonical truth/detection schema;
- `aihub/wakeword/v4_benchmark_contract.py` — schema/contract validation;
- `aihub/wakeword/v4_eval.py` — one-to-one matching, recall/miss/FPPH, confidence intervals, latency/group breakdowns, deterministic threshold sweep;
- `aihub/wakeword/v4_replay.py` — deterministic replay driver;
- `aihub/wakeword/v4_ring_buffer_logger.py` — privacy-first candidate/manual-miss reference capture.

`v4_eval.py` remains authoritative for mixed and long household recordings. It already supports:

- 500 ms pre / 1500 ms post matching tolerance by default;
- one detection per truth event;
- duplicate/unmatched detections as false positives;
- recall and miss rate;
- FPPH / false alarms per day;
- Wilson recall confidence interval;
- Poisson false-positive-rate confidence interval;
- P50/P95/mean latency;
- breakdowns by phrase, speaker, condition, room, background, distance, direction, voice level, self-TTS and time bucket;
- threshold sweep.

Long-recording negative exposure must exclude intentional invocation windows according to the v4 benchmark contract.

## Android wake evidence bridge

The new Android code is a bridge into the canonical v4 stack, not a replacement for it.

### `WakeBenchmarkHarness`

Replays short recorded PCM16 cases as canonical `PcmFrame`s into a microphone-free `WakeDetector` and scores detections in **sample time**.

Why sample time: offline replay speed and detector `SystemClock` timestamps are not a stable latency reference. Detection position is therefore the end-sample index of the frame that emitted `WakeDetection`.

Default match windows mirror `v4_eval.py`: 500 ms early / 1500 ms late.

Use this harness for short/device same-PCM regression and detector adapter tests. Use `v4_eval.py` for canonical long/mixed household release scoring.

### `WakeBenchmarkRecords`

Emits Android truth/detection JSONL compatible with the existing `v4_benchmark_schema.json` fields, including model/version/provenance identifiers and optional sample-index provenance.

Optional schema fields are omitted when absent instead of being serialized as invalid `null` values.

Android `WakeThresholdSweep` is a deterministic local/debug preview only. It does not replace the frozen-set threshold-selection and release report in `v4_eval.py`.

### `WakeDiagnosticCaptureBuffer`

Provides bounded, in-memory candidate/manual-miss capture:

- reuses `AudioEngine.readPreRoll` rather than owning a second continuous ring;
- appends bounded post-roll from forwarded `PcmFrame`s;
- never opens `AudioRecord`;
- performs no filesystem I/O;
- marks post-roll PCM discontinuity and incomplete flushes explicitly.

A debug/benchmark surface may persist a returned clip only under the benchmark consent/retention policy.

## Existing openWakeWord compatibility evidence

`aihub/wakeword/OPENWAKEWORD_REAL_REPLAY_EVIDENCE.md` already proves deterministic compatibility of the current Okja replay path with openWakeWord; do not repeat basic feasibility work.

Recorded compatibility inputs include:

- runtime: `openwakeword==0.6.0`, CPU ONNX;
- official openWakeWord feature-model assets pinned by SHA-256;
- Okja classifier/model pinned by SHA-256;
- explicit NumPy initialization seed because openWakeWord 0.6.0 primes its feature buffer from randomized PCM;
- successful three-repeat deterministic replay.

This evidence proves **runtime/model compatibility only**. The single positive replay is not a production wake-quality benchmark, and early output from seeded feature history must not be interpreted as quality evidence.

Therefore the next openWakeWord milestone is:

**Android caller-owned PCM inference + canonical v4 same-corpus comparison**, not another generic openWakeWord feasibility probe.

## Wake candidate order

### 1. openWakeWord — first open Stage-A implementation path

Purpose:

- run the already-proven feature/classifier pipeline from caller-owned Android PCM;
- establish an open/custom high-recall Stage-A baseline;
- generate real candidate clips for Stage-B verifier training/evaluation.

The Android implementation must not import an engine wrapper that silently owns microphone capture. Reuse/adapt inference internals only if they preserve Okja's one-microphone-owner invariant and license requirements.

### 2. Porcupine low-level PCM — independent commercial benchmark control

Use only the low-level `Porcupine` API with caller-owned PCM. Do not use `PorcupineManager` in Okja's production topology because it integrates microphone capture.

Porcupine has credible Android and Korean custom-wake support, making it a useful independent benchmark. It also requires an AccessKey/vendor dependency, so benchmark success does not automatically satisfy the final open/local product constraint.

### 3. sherpa-onnx KWS — longer-term open runtime candidate

sherpa-onnx provides Android keyword-spotting infrastructure, but Okja should not assume Korean readiness until an appropriate Korean/Okja model or tokenization path is demonstrated and benchmarked.

## Wake phrase matrix

Primary production benchmark phrase:

- `옥자야`.

Short alias/control:

- `옥자`.

Later optional variants:

- `헤이 옥자`;
- `오케이 옥자`;
- English variants only if product requirements justify them.

The shorter `옥자` must be tested especially aggressively against conversational mentions and similar-sounding background speech.

## Wake condition matrix

At minimum vary:

| Dimension | Conditions |
|---|---|
| Distance | 0.5 m / 2 m / 4 m |
| Direction | front / side / behind |
| Voice | normal / quiet / elderly-soft |
| Environment | quiet / TV / Korean news / drama / YouTube / kitchen / AC-fan |
| Context | intentional wake / mention of Okja / similar-sounding words |
| Device audio | idle / Okja TTS / controlled TV playback |
| Speaker | primary senior / family / other speaker |
| Time/state | day / evening / screen-off ambient |

## Wake measurements

Top-line:

- recall;
- FRR = `1 - recall`;
- false activations/hour;
- mean hours between false activations;
- P50/P95 detection latency.

Breakdowns:

- phrase-specific recall;
- speaker-specific recall;
- distance-specific recall;
- TV-on recall;
- TV/background false activations/hour;
- self-TTS false activations/hour;
- Stage-A candidate rate/hour;
- Stage-B rejection rate;
- CPU average/peak;
- PSS/RSS average/peak;
- battery/thermal after correctness gates pass.

Near-threshold rejected candidates should be preserved as review/training evidence when consent and retention rules permit it.

## Long-negative statistical gate

A short household test cannot certify a rare false-wake rate.

For zero observed false activations, the approximate 95% Poisson upper bound is:

`lambda_95 ~= 3 / T_hours`.

Therefore:

- zero events in 24 h only supports an upper bound around 0.125/hour;
- zero events in ~300 h supports an upper bound around 0.01/hour.

Progression:

```text
10 min developer replay
  -> 1 h controlled room
  -> 24 h household smoke
  -> 100 h multi-condition negative
  -> 300+ h release-gate negative
  -> multi-household pilot
```

## Initial production-oriented gates

Target device: Galaxy Z Fold4 / SM-F936N.

Architecture gates:

- one active `AudioRecord` throughout wake -> recognition;
- duplicate physical execution = **0**;
- production system recognition cue = **0**;
- physical execution after PCM discontinuity = **0**.

Physical-command gates:

- representative correct command execution: target **>=98%**;
- opposite-action physical execution: **0 observed**, release-blocking;
- wrong-target physical execution: **0 observed**, release-blocking;
- false physical execution from non-command/false wake: **0 observed**, release-blocking;
- uncertain/conflicting evidence must abstain.

Wake gates are staged rather than one final number:

- developer/early device gate: useful recall and a false-activation rate low enough to justify longer testing;
- 24 h smoke: no catastrophic TV/self-TTS behavior;
- 100 h: stable threshold and condition breakdowns;
- 300+ h release gate: target evidence consistent with <~0.01 false activations/hour when zero false events are observed.

Do not infer production readiness from the three-phrase ASR corpus, a single openWakeWord replay, or a short wake session.

## TTS self-trigger benchmark

First production implementation is half-duplex: new wake/capture entry is blocked while Okja TTS is active.

Still benchmark self-playback explicitly because Stage-A candidates during TTS are useful hard negatives for Stage B even when the controller prevents final activation.

Full-duplex/AEC is deferred until baseline correctness is stable.

## Android lifecycle benchmark

Foreground-service lifecycle is measured after recognition correctness is credible.

The microphone foreground service must be launched from a visible/user-authorized flow compatible with modern Android while-in-use microphone restrictions.

Measure separately:

- restart/recovery behavior;
- screen-off stability;
- Samsung background-process behavior;
- Bluetooth/headset routing;
- sustained CPU/PSS;
- battery/thermal.

Do not combine lifecycle failures with wake-model accuracy statistics.

## Runtime optimization order

Use CPU / standard runtime first.

QNN/NPU/other acceleration is a later optimization after command correctness, wake reliability, continuity, lifecycle, and battery gates pass.

## Model provenance

Provisioning/replay scripts record archive/model/runtime SHA-256 hashes. First-seen digests are benchmark provenance, not release trust anchors.

Before a release candidate, reviewed model/runtime digests must be promoted into a pinned release manifest.
