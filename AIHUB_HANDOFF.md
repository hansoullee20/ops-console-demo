# AI Hub / Okja — Project Handoff

**Last updated:** 2026-08-13 (KST)
**Repository:** `hansoullee20/ops-console-demo`
**Working branch:** `aihub-voice-test`
**Project directory:** `aihub/`
**Wake-word work:** `aihub/wakeword/`
**Start here in a new session:** read this file first. If chat memory conflicts with Git, Git is source of truth.

> **CURRENT CHECKPOINT:** Okja v3 remains rejected as a deployable model. Reusable evaluator, benchmark contract, diagnostic ring buffer and deterministic replay harness now exist. Real LiveKit replay run `31669141305` and alternative openWakeWord replay run `31670716561` used the exact same pinned v3 classifier/audio SHAs and were deterministic over three repeats per threshold. Their engine-specific scores differ, which is compatibility evidence rather than a changed v3 quality verdict. The alternative-runtime portion of G2.5 is complete; G2.5 stays open only until a pinned real v4 classifier replays the identical audio SHA. Existing Android SpeechRecognizer remains the working control/fallback.

## Active continuation log — 2026-08-13

- Completed subtask: replay the exact pinned v3 ONNX and WAV through a second fully local/open runtime, openWakeWord `0.6.0`.
- Compatibility basis: openWakeWord accepts custom ONNX classifiers, derives the temporal embedding length from the model input shape, and processes 16 kHz PCM in 1280-sample (80 ms) streaming frames. The LiveKit v3 classifier uses a 16-frame × 96-feature input.
- Evidence policy: pin package version, model/audio hashes, thresholds, frame size and adapter source; require three identical replays before recording evidence.
- Closure guard: this can satisfy the alternative-runtime portion only. G2.5 must remain open until a real v4 classifier also replays the identical audio SHA.
- First real run `31669829292` failed after package installation and input SHA verification because the openWakeWord `0.6.0` wheel did not contain `melspectrogram.onnx` or `embedding_model.onnx`. This is a missing-runtime-resource failure, not a classifier incompatibility result.
- First recovery: fetch the two official openWakeWord `v0.5.1` release assets separately, pass their paths explicitly and reject missing files. Do not use an untracked mutable download into `site-packages` as benchmark evidence.
- Recovery adapter commit `0343ef8` requires both feature-model paths explicitly and fails closed if either is absent. Evaluator run `31670415113` passed all 32 tests.
- Second real run `31670415071` loaded the explicit feature models, then failed the three-repeat determinism guard at threshold `0.50`: attempt 1 emitted one detection and attempt 2 differed. openWakeWord `0.6.0` seeds its feature buffer from four seconds of random PCM on every model construction, so this is an uncontrolled runtime-initialization result, not benchmark evidence.
- Final recovery commit `4c59e9e` pins `embedding_model.onnx` SHA-256 `70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f`, pins `melspectrogram.onnx` SHA-256 `ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f`, and makes NumPy initialization seed `0` an explicit adapter/manifest input.
- Successful real run `31670716561`: all hashes verified and both thresholds were 3/3 deterministic. Threshold `0.50` detected once at 1280 ms with score `0.5055038929`; threshold `0.06` detected once at 560 ms with score `0.0630315244`. Unit run `31670716607` passed all 32 tests.
- Gate impact: the G2.5 alternative-runtime portion is complete, but G2.5 stays unchecked until a pinned real v4 classifier replays the exact audio SHA. G2.16 also stays unchecked because one positive compatibility replay is not a full alternative-engine benchmark. Durable details: `aihub/wakeword/OPENWAKEWORD_REAL_REPLAY_EVIDENCE.md`.

### G1 gate audit — active

- Existing durable evidence supports G1.1, G1.4, G1.6, G1.8 and G1.9: run `31612771436` cleanly generated pinned Chatterbox `0.1.7` and Kokoro `0.9.4` artifacts; all 10 clips passed WAV QC/leakage; the checker explicitly reports unavailable speaker/engine holdouts as `not_evaluable`. MeloTTS run `31615755020` independently passed its explicit engine holdout, WAV QC and leakage checks.
- Per-clip manifests already contain the G1.3 provenance fields, but `v4_dataset_schema.json` was not enforced by any workflow. Current implementation work adds a fail-closed `validate-manifest` command, requires `source_license`, tests invalid/missing provenance, and inserts validation into Kokoro, Chatterbox and MeloTTS smoke jobs.
- Keep G1.2 open: top-level packages are pinned, but there is no complete transitive lock proven from clean CI. Keep G1.5 open because Chatterbox Korean positives failed human pronunciation review. Keep G1.7 open until the current `if: always()` diagnostic path is demonstrated on a post-fix failing run. Keep G1.10 open per the human-QC policy.
- Do not mark the audited gates until the new unit test and all three real smoke jobs pass with manifest validation enabled.

---

## 0. Fast restart

```bash
git clone https://github.com/hansoullee20/ops-console-demo.git
cd ops-console-demo
git checkout aihub-voice-test
cat AIHUB_HANDOFF.md
```

Important paths: `AIHUB_HANDOFF.md`, `AIHUB_V4_TEST_PLAN.md`, `aihub/README.md`, `aihub/app/`, `aihub/phone/`, `aihub/wakeword/`, `.github/workflows/aihub-build.yml`, `.github/workflows/okja-wakeword-v2.yml`, `.github/workflows/okja-wakeword-v3.yml`.

## 1. Product goal

Build a DIY, always-on Android smart display / voice assistant / family-care hub named **옥자 / Okja**. Target is inexpensive Nest-Hub-like standalone Android hardware with display, front camera, mic, speaker and Wi-Fi; local always-listening wake word; cloud reasoning through existing subscription/official agent paths where practical; later Voice ID, room/device context, companion phone, family messaging, alerts, TV/home automation.

**One app/firmware, not separate grandmother/personal products.** The same product adapts presentation, permissions and content using speaker/user identity plus room/device identity.

Original rough completed-unit cost target: ~KRW 40,000. Do not select final hardware until the always-on stack is measured on the Fold4.

## 2. Tested environment

```text
Samsung Galaxy Z Fold4 / SM-F936N
Android 16, ARM64/aarch64
Snapdragon 8+ Gen 1 class
~10 GiB RAM visible to Termux; 8 GiB swap in test environment
not rooted
Termux Google Play build googleplay.2026.06.21; termux-api installed
```

Provisional hardware envelope only: ARM64, 4 GB real RAM preferred, 3 GB only if measured sufficient, 2 GB risky, ~32 GB storage likely enough. Never count virtual RAM as physical RAM.

## 3. Working assistant path

```text
Android SpeechRecognizer
→ command text
→ length-prefixed TCP 127.0.0.1:8765
→ Ubuntu PRoot inside Termux
→ persistent Claude Agent SDK client
→ response
→ Android TTS
```

Protocol: 4-byte big-endian payload length + UTF-8 JSON. Persistent Claude is essential: observed first request ~2.89 s and later ~1.5 s in one test; fresh one-shot `claude -p` was ~19–34 s. Startup peak RSS ~297–299 MB.

Bridge files: `aihub/phone/aihub_bridge.py`, `aihub/phone/start_bridge.sh`. Known bridge issue: clients initialize before TCP server opens, so SDK initialization timeout can prevent server availability. Future fix: lazy/resilient independently recoverable clients.

## 4. Android state

Key Java files under `aihub/app/src/main/java/com/soul/aihub/`:

```text
MainActivity.java
PerfActivity.java
PerfMeter.java
StableTemplateWakeActivity.java
TemplateWakeActivity.java
```

Namespace/app ID `com.soul.aihub`.

Existing SpeechRecognizer wake path works. Preserve it as control/fallback while local KWS is researched. Do not destabilize this path for experiments.

## 5. Wake/product identity

Canonical identity: **옥자 / Okja**. Desired eventual variants: `옥자`, `옥자야`, `Okja`, `Hey Okja`, `Okay Okja`, `헤이 옥자`, `오케이 옥자`, normalized to one `WAKE_OKJA` event.

Device identity = where the device is / what it controls. User identity = who is speaking. Speaker ID is not a security guarantee; TV/replay can spoof it, and emergency phrases must not be suppressed solely due to low speaker-ID confidence.

## 6. Wake-engine chronology

- **Android SpeechRecognizer:** proved complete hands-free interaction. Control/fallback, not desired final low-power engine. Earlier PERF CPU figures were short process snapshots, not sustained system averages.
- **MFCC + DTW template:** proved local wake-style processing on Fold4; enrollment UX is unattractive for final consumer use.
- **Vosk probe:** `vosk-model-small-ko-0.22` vocabulary contained `옥자`, `헤이`, `오케이`, `허브`. Feasibility probe, not current final KWS.
- **Requirement:** final wake engine must be fully free/open-source/local. Porcupine/Eagle/AccessKey-style dependency rejected.
- Candidates considered: LiveKit WakeWord, microWakeWord, openWakeWord, sherpa-onnx, Vosk.

## 7. Measurement protocol

Use same phone/screen/microphone/room. Measure >=10 min idle; CPU now, 1-min avg, full-run avg, peak; PSS avg/peak; wake attempts/success/miss; false wakes; TV/audio false activations; latency. Use >=20 real wake attempts and 5–10 full wake→command→Claude→TTS→wake cycles. Do not choose hardware from short snapshots.

## 8. LiveKit v2 — pipeline success, model failure

```text
run ID: 31563550569
targets: 옥자, 옥자야, Hey Okja
small conv_attention; 6000 steps
ACAV100M training samples: 0
validation: 128 positive / 30,404 negative / 16.89 h
threshold .50: Recall 13.28%, FPPH 2.6641
```

Lower thresholds improved recall but caused massive false positives. v2 is not deployable. Main weaknesses: effectively one synthetic Korean speaker; limited/mixed-language positive base; no ACAV general-speech training features; training warned about missing general speech; earlier background acquisition had a 429 failure.

## 9. LiveKit v3 — Korean-only diagnostic COMPLETE

Purpose: simplify to `옥자` only, increase synthetic positive volume and strengthen phrase/general Korean negatives. Diagnostic, not production model.

Commits:

```text
cab553adce4670c9381327d7c5a4c208ae27c3d9  v3 dataset generator
25b6f3fc218a5b9d33f4e79b339e47709a35902b  v3 config
a128dd9a269e2b99dd7081abcbe9edcc545379e0  v3 workflow
```

Workflow result:

```text
Train Okja Wakeword v3 Korean Probe
run ID: 31583273747
completed / success
```

Held-out evaluation:

```text
positive: 512
negative: 31,236
validation duration: 17.35 h
threshold .50: Recall 4.6875%, FPPH 0.0
trainer optimal threshold .06: Recall 85.3516%, FPPH 310.0269
```

**Verdict: FAIL / NOT PROMISING for Android integration.** The useful-recall region produces catastrophic false positives. Do not tune threshold, add steps, or integrate v2/v3.

### Deterministic real-audio replay evidence

```text
adapter/test commit: 0d6f7188fc15d05a31045944b9d4d240877d3148
unit-test run: 31669141480 (success; 25 tests)
real replay run: 31669141305 (success)
runtime: livekit-wakeword 0.2.1
model SHA-256: 3cff1a6c54e2eece99f3b61e0238a51b317019d5c1bf214e2c1bddf80998bb7b
audio SHA-256: a9551898057bfc145002e7e4c0abffff759f450a67e706465d70a18953c5f2a0
threshold .50: 0 detections, identical across 3 repeats
threshold .06: 1 detection at 2000 ms, score 0.1658398509, identical across 3 repeats
```

Full record: `aihub/wakeword/V3_REAL_REPLAY_EVIDENCE.md`. This is v3-path evidence only, not completion of G2.5.

## 10. Strategy change after v3

The project deliberately changed from “keep training until validation looks better” to **learn from real product conditions and diversify the synthetic domain before the next serious model run**.

Two complementary data ideas are now part of the plan:

1. **Real household benchmark:** record long ambient sessions (eventually ~24 h, potentially multiple devices/locations), include intentional Okja utterances with rough timestamps, and run candidate models offline over the exact same recordings. This becomes a fixed benchmark for false triggers, misses, score distributions and environmental failure modes.
2. **Diverse synthetic corpus:** use multiple permissively licensed TTS engines/voices, modern owned conversational scripts, Korean and English wake variants, hard phonetic negatives and controlled acoustic augmentation. Avoid another single-speaker synthetic loop.

A future on-device shadow logger is also useful: rolling PCM buffer, save ~3 s before + ~2 s after triggers, metadata, manual miss capture and event review. However, long external recordings can establish the benchmark before that app exists.

## 11. v4 source/license work already completed

Added on `aihub-voice-test`:

```text
41a6391  AIHUB_V4_TEST_PLAN.md
f13ab6f  v4_sources_manifest.yaml
5e96712  build_v4_scripts.py
```

Current conservative source direction:

- Chatterbox Multilingual: Korean + English synthetic source; permissive license verified during source review.
- MeloTTS: retain only as one source, not the dominant Korean speaker domain.
- Ppaso-TTS: candidate independent Korean synthetic source; keep license/model provenance recorded in manifest.
- Kokoro-82M: English speaker/voice diversity for `Okja`, `Hey Okja`, `Okay Okja`.
- Exclude sources with non-commercial or otherwise incompatible model/output terms from the durable product dataset.
- Do not assume “open-source code” means model weights, voices and generated output are automatically safe for commercial product training.

Text strategy:

- **Primary:** scripts written/generated specifically for this project, so we own/control the text corpus and can model modern household conversation directly.
- Public-domain literature is optional diversity material, not the core corpus. It should only be added after work-specific rights verification.
- Keep `mention_context` separate from ordinary negatives. Example: “어제 옥자라는 영화를 봤어” contains the actual acoustic keyword and is a product-policy/context test, not a normal negative.

## 12. v4 evaluation philosophy

Do not optimize for a pretty synthetic validation score. The question is whether the acoustic concept generalizes beyond a specific TTS engine/voice.

Required evaluation layers:

```text
TEST A — held-out synthetic speakers
TEST B — held-out TTS engine
TEST C — real human Okja utterances
TEST D — fixed long household recording benchmark
```

`TEST D` must remain outside training. Future LiveKit versions and alternative KWS engines should compete on the same benchmark.

## 13. THREE ACTIVE WORK TRACKS

### Track A — Wakeword / v4 data + model

Goal: create a genuinely more diverse diagnostic corpus before another expensive training iteration.

Planned sequence:

1. Finalize dataset schema and provenance fields.
2. Add TTS generation adapters for approved Korean/English engines.
3. Generate a **tiny** smoke corpus first.
4. Human-listen to samples by engine/voice/phrase.
5. Only after QC passes, scale corpus generation.
6. Train v4 sanity model.
7. Evaluate against held-out voices/engine, then real recordings and household benchmark.
8. Compare against at least one alternative local KWS rather than optimizing LiveKit indefinitely.

### Track B — Test / evaluation infrastructure

This must exist before large-scale v4 generation.

Required pieces:

- clip manifest fields: language, text/phrase, class, TTS engine, voice, script ID, source/license provenance, augmentation, parent/base audio ID, split;
- deterministic train/validation/test splitter;
- entire-speaker and preferably entire-engine holdout support;
- leakage checker so derivatives of the same base clip cannot cross splits;
- automatic WAV/audio QC: readable file, sample rate/channels, duration, silence, clipping, malformed output;
- pronunciation QC workflow for initial samples;
- baseline evaluator capable of running **v3 ONNX** on future test corpora before retraining;
- automatic threshold sweep / Recall / miss / FPPH report;
- later long-recording evaluator that scans ambient audio and exports timestamped trigger windows/scores;
- reproducible summary output so v3/v4/alternative KWS can be compared on identical data.

Do not create tens of thousands of TTS clips before the tiny end-to-end smoke pipeline passes.

### Track C — Final product UI/UX

This is now an explicit parallel track, not something to postpone until the model is finished. UI state requirements influence backend events and product architecture.

**Core product principle:** voice-first, touch-second. Okja should feel like an ambient appliance/smart display, not like a generic Android tablet app.

Shared interaction states:

```text
Ambient / Home
Listening
Thinking / Executing
Answer / Action result
Manual dashboard
Microphone off / offline / error states
```

Microphone/listening state must always be unambiguous.

#### Grandmother / senior presentation

The grandmother experience should be extremely simple and minimal, with no clutter or “cheap tablet UI” feel.

- very large readable typography;
- high information hierarchy and large touch targets;
- very few choices per screen;
- ambient home shows only the most useful information;
- likely primary content: large clock/date/weather, medication/reminders, family/contact access, simple TV/home actions and urgent help;
- one screen = one obvious action wherever possible;
- avoid dense menus, tiny icons and decorative complexity.

#### Personal presentation

Same product and same design language, but denser information can adapt to the user's lifestyle.

Potential ambient/home information:

- today's schedule;
- tasks/reminders;
- weather;
- home/device status;
- personal phone/device finding;
- relevant messages/notifications;
- context-aware cards.

Speaker identity + room/device identity determine what content/actions are shown; they do not create a separate app build.

#### Common wake transition

Regardless of profile, calling Okja should move into a shared simple listening state, followed by thinking/executing and result states. Personalization changes content and permissions, not the fundamental interaction grammar.

#### UI work not yet decided

Do **not** prematurely lock color palette, icon set, animation style or visual branding. First lock information architecture, interaction states, senior readability requirements and personal dashboard priorities. Then create visual mockups.

## 14. Recommended parallel execution from this checkpoint

Two streams can proceed at the same time:

```text
STREAM 1
Track A + Track B
v4 data pipeline + evaluation infrastructure
        ↓
tiny end-to-end smoke test
        ↓
scaled v4 experiment

STREAM 2
Track C
product information architecture
        ↓
grandmother home mockup
personal home mockup
shared listening/thinking/result mockups

STREAM 1 + STREAM 2
        ↓
Android integration / Fold4 shadow testing
        ↓
real household benchmark
        ↓
model + UX iteration
```

The test UI and final product UI are different artifacts. Test tooling may expose scores, thresholds, labels, CPU/RAM and event clips. Final product UI should hide that complexity.

## 15. Immediate next actions

1. **Alternative-runtime replay completed:** keep G2.5 unchecked only for the real v4 replay; keep G2.16 unchecked until a full shared benchmark exists.
2. Reconcile G1.1–G1.10 against the existing smoke artifacts and human-QC notes. Mark only gates with durable clean-CI evidence; list the exact missing evidence for the rest.
3. Close the remaining automatable G1 gaps—dependency pins, per-clip provenance, failure artifact retention, holdout reporting, WAV QC and leakage reporting—then rerun a tiny approved-source smoke corpus end to end.
4. Train only a small v4 sanity classifier after G1.1–G1.10 genuinely pass. Replay audio SHA `a9551898...` through that pinned model with `v4_replay.py` to close G2.5.
5. In parallel, collect the human-owned TEST C/TEST D recordings needed for real-human and household false-trigger evidence. Do not launch large v4 generation before the G1 gate passes.

## 16. Do not repeat

- Do not integrate v2/v3 just because ONNX export succeeded.
- Do not confuse pipeline success with model quality.
- Do not threshold-tune v3: useful recall costs ~310 FPPH.
- Do not assume more steps solve a data-domain problem.
- Do not treat rate/pitch variants of one synthetic voice as real speaker diversity.
- Do not generate a huge synthetic corpus before split/leakage/audio/pronunciation QC exists.
- Do not let train/test share derivatives of the same base audio.
- Do not evaluate only on voices/engines seen during training.
- Do not let public-domain literature dominate modern conversational negatives.
- Do not select hardware before sustained Fold4 measurements.
- Do not count virtual RAM as real RAM.
- Do not interpret grandmother/personal presentation as separate products.
- Do not make the senior UI dense or menu-heavy.
- Do not spawn fresh Claude CLI per request.
- Do not rely on chat memory when Git differs.

## 17. Immediate restart instruction

> Open `hansoullee20/ops-console-demo`, branch `aihub-voice-test`, and read `AIHUB_HANDOFF.md` first. v3 failed as a deployable wake model. Current work is three parallel tracks: (A) v4 diverse synthetic/real-data wakeword work, (B) reusable test/evaluation infrastructure, and (C) final Okja UI/UX with an ultra-simple large-type senior presentation and a richer personal lifestyle dashboard. Build test infrastructure + tiny smoke corpus before large v4 training, while designing product information architecture in parallel. Preserve Android SpeechRecognizer as the working control/fallback.
