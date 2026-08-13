# AI Hub / Okja — Project Handoff

**Last updated:** 2026-08-13 KST  
**Repository:** `hansoullee20/ops-console-demo`  
**Working branch:** `aihub-voice-test`  
**Project directory:** `aihub/`  
**Wake-word work:** `aihub/wakeword/`  
**Canonical execution tracker:** `AIHUB_MASTER_EXECUTION_CHECKLIST.md`

**Start here in a new session:** read this file, then the master checklist, then verify the current branch HEAD. Git is the source of truth if chat memory conflicts.

## Current checkpoint

Checkpoint immediately before this documentation refresh: `6486a778e4098173bfc1a5e556587c75e66d2e84`.

The product foundation and core voice-contract work are substantially ahead of the older wakeword-only handoff state:

- Android SpeechRecognizer → localhost bridge → persistent Claude Agent SDK → Android TTS remains the working control/fallback path.
- LiveKit v3 remains rejected as a deployable wake model. Do not threshold-tune or integrate it.
- G3.1–G3.6, G3.8–G3.11, G3.23, G3.31 and G3.32 have durable evidence where marked complete in the master checklist.
- **G3.2 is closed:** recognizer lifecycle, intent and explicit confirmation events are produced on the real path; physical device execution remains separate.
- **G3.31 is closed at software-contract level:** READY/LISTENING/THINKING/MIC_OFF/OFFLINE_DEGRADED/ERROR_RECOVERY are explicit; MIC_OFF destroys microphone access and bridge/recognizer/TTS failures enter explicit degraded/recovery states.
- **G3.32 is closed:** TCP `127.0.0.1:8765` binds before Claude client initialization; clients are lazy, per-profile, concurrency-safe and retryable after initialization failure.
- G2.8 instrumentation is ready, but target Fold4 evidence has not been collected yet.
- G1 large generation remains locked because G1.10 human listening is incomplete and failed Chatterbox Korean positives remain rejected under G1.5.
- G2.5 remains open only until a pinned real v4 classifier replays the same pinned real audio through the deterministic replay harness.

## Next action / execution order

1. **Fold4 evidence first.** Use one structured target-device session to collect the >=20 accepted wake attempts needed by G2.8 and the >=20 wake/full-cycle evidence for G3.30. Observe sustained idle behavior for G3.29 during the same session where practical.
2. **Continue the same instrumented build toward G3.33.** Leave it running for the 24-hour app-stability smoke and preserve logs before changing code.
3. **Repair only evidenced failures.** If the Fold4 run exposes a defect, fix that defect and rerun the affected gate before unrelated feature work.
4. **Finish wake/data prerequisites.** Complete G1.10 human listening disposition and produce/replay the pinned real v4 classifier required by G2.5. Do not unlock large generation while G1 is blocked.
5. **Then resume G3 product integration.** Senior/personal Android UI and real TV/AC/phone-finder adapters follow after the current reliability/data blockers are resolved.

## Do not start yet

Unchecked later items are not automatically the next task. Do not jump to G4 pilot claims, G5 presence sensing, G6 fall/night sensing, or hardware cost-down merely because those checklist entries are open. The current critical path is the target-device evidence plus the remaining G1/G2 prerequisites above.

## Fast restart

```bash
git clone https://github.com/hansoullee20/ops-console-demo.git
cd ops-console-demo
git checkout aihub-voice-test
cat AIHUB_HANDOFF.md
cat AIHUB_MASTER_EXECUTION_CHECKLIST.md
```

Then verify:

```bash
git status -sb
git rev-parse HEAD
```

## Product goal

Build one DIY, always-on Android smart display / voice assistant / family-care hub named **옥자 / Okja**. It is one app/firmware with senior and personal profiles, not separate products. The same product adapts presentation, permissions and content using user/profile and room/device identity.

The final hardware target remains inexpensive Nest-Hub-like standalone Android hardware with display, front camera, microphone, speaker and Wi-Fi. **Do not select final hardware before sustained Fold4 measurements.**

## Tested environment

```text
Samsung Galaxy Z Fold4 / SM-F936N
Android 16, ARM64/aarch64
Snapdragon 8+ Gen 1 class
~10 GiB RAM visible to Termux; 8 GiB swap in test environment
not rooted
Termux Google Play build googleplay.2026.06.21; termux-api installed
```

Never count virtual RAM as physical RAM.

## Working assistant path

```text
Android SpeechRecognizer
→ command text / versioned voice events
→ length-prefixed TCP 127.0.0.1:8765
→ Ubuntu PRoot inside Termux
→ persistent Claude Agent SDK client
→ response
→ Android TTS
```

Protocol: 4-byte big-endian payload length + UTF-8 JSON.

Bridge files:

- `aihub/phone/aihub_bridge.py`
- `aihub/phone/start_bridge.sh`
- `aihub/phone/okja_lazy_agent_pool.py`

The old bridge-startup defect is **fixed** under G3.32: server bind no longer waits for eager Claude client startup.

## Current core voice/product evidence

### G3.1 — versioned event envelope

Commit `a1aa9c3` defines the strict `okja.event.v1` envelope, Android/Python validation and correlated transcript/assistant transport. Contract run `31680385188` and APK run `31680385242` are green.

### G3.2 — core voice lifecycle

- `88fd83f`: wake candidate/detected/rejected, listening start/stop/failure and transcript partial/final/failure in a bounded volatile ledger.
- `2f2f892`: exact intent requested/resolved/failed plus explicit two-turn confirmation requested/accepted/rejected on the real bridge.
- Contract run `31692595222` and APK run `31692595239` are green.
- Physical TV/AC/phone-finder execution is deliberately not claimed without adapters.
- Durable record: `aihub/phone/G3_2_CORE_VOICE_EVIDENCE.md`.

### G3.3 / G3.8 — device command boundary

Commit `f2a41f6` provides strict TV/AC/phone-finder command validation, durable idempotency and explicit success/failure events. Washer remains reserved/disabled. Contract run `31681395404` and APK run `31681395431` are green. Physical integrations remain separate gates.

### G3.4 — care/family event contract

Commit `bec1fac` defines consent-aware wellness, symptom-record, arrival/departure, ETA and notification event contracts; emergency events are guarded separately by `15be362`. Contract run `31683811764` and APK run `31683811759` are green. UI, sensors and delivery remain separate.

### G3.5 / G6.18 — guarded emergency boundary

Commit `15be362` prevents LLM/agent output from directly transitioning or escalating emergency state. Only family notification is allowlisted; automatic 119/emergency-services behavior remains disabled. Safety run `31682270351` and APK run `31682270376` are green.

### G3.6 / G3.9 / G3.10 — shared profiles and consent

Commit `1434c3f` defines one senior/personal schema with accessibility preferences, device capability choices, caregiver notification preferences and separate essential/health/caregiver/camera/research consent records. Run `31682851423` and APK run `31682851417` are green.

### G3.31 — voice trust states

The live activity now has READY, LISTENING, THINKING, MIC_OFF, OFFLINE_DEGRADED and ERROR_RECOVERY. MIC_OFF destroys/nulls `SpeechRecognizer` and blocks both manual and automatic input. Final integration run `31693447185` and APK run `31693447195` are green. Durable record: `aihub/phone/G3_31_VOICE_TRUST_STATE_EVIDENCE.md`.

### G3.32 — lazy/resilient bridge startup

`okja_lazy_agent_pool.py` keeps profile factories inert until first use. The localhost server binds first; client initialization is per-profile, deduplicated under concurrency and failed initialization is not cached, so later requests can retry. Runs `31693869837` and `31693994203` are green. Durable record: `aihub/phone/G3_32_BRIDGE_STARTUP_EVIDENCE.md`.

## Wakeword status

### LiveKit v2/v3

v2 and v3 proved the pipeline but failed model quality. v3 held-out evaluation reached useful recall only at catastrophic false-trigger rates (~310 FPPH at trainer threshold `.06`). Verdict remains **FAIL / NOT PROMISING for Android integration**.

Pinned real v3 replay evidence:

```text
runtime: livekit-wakeword 0.2.1
real replay run: 31669141305
model SHA-256: 3cff1a6c54e2eece99f3b61e0238a51b317019d5c1bf214e2c1bddf80998bb7b
audio SHA-256: a9551898057bfc145002e7e4c0abffff759f450a67e706465d70a18953c5f2a0
threshold .50: 0 detections, identical across 3 repeats
threshold .06: 1 detection at 2000 ms, score 0.1658398509, identical across 3 repeats
```

OpenWakeWord alternative-runtime replay run `31670716561` is also deterministic over three repeats using pinned feature-model hashes and initialization seed. This completes the alternative-runtime portion of G2.5 only; G2.5 remains open for real v4 replay, and G2.16 remains open for a full shared benchmark.

## v4 data status

- Runtime dependencies for Kokoro, Chatterbox and MeloTTS are locked and clean-CI reproducible.
- Provenance, WAV QC, leakage checks and failed-run diagnostic preservation are implemented.
- MeloTTS Korean smoke is human-approved for initial v4 data.
- Chatterbox Korean positive pronunciation/naturalness failed human review and remains quarantined.
- `v4_scripts.csv` contains 425 unique bilingual scripts with deterministic IDs and pre-generation train/validation assignment.
- Large generation remains locked until the exact G1 requirements in the master checklist are satisfied.

Key records:

- `aihub/wakeword/V4_MELOTTS_HUMAN_QC.md`
- `aihub/wakeword/V4_PRONUNCIATION_QC.md`
- `aihub/wakeword/V4_PRONUNCIATION_QC_LOG.md`
- `AIHUB_V4_TEST_PLAN.md`

## Fold4 measurement work now required

G2.8 instrumentation already records monotonic VAD onset, segment end and decision timestamps, device/app/session identity and exact enrolled-template SHA. The procedure is in:

`aihub/wakeword/V4_ANDROID_LATENCY_MEASUREMENT.md`

The gate requires at least 20 accepted attempts from one valid target-device session before P50/P95 latency can be claimed.

Combine this, where practical, with:

- G3.29 sustained idle measurement;
- G3.30 >=20 wake attempts + full cycles;
- G3.33 24-hour app stability smoke;
- later G7 resource-envelope measurements.

## UI/product direction

Voice-first, touch-second. Shared interaction grammar:

```text
Ambient / Home
Listening
Thinking / Executing
Answer / Action result
Manual dashboard
Microphone off / offline / error states
```

Senior presentation: very large readable typography, large touch targets, minimal choices, simple family/home actions and deterministic emergency UI. Personal presentation uses the same design language with denser schedule/tasks/home-state content.

Information architecture exists, but later visual/UI implementation gates remain governed by the master checklist. Do not interpret those open items as permission to skip the current Fold4/G1/G2 blockers.

## Do not repeat

- Do not integrate or threshold-tune LiveKit v2/v3.
- Do not confuse pipeline success with model quality.
- Do not assume more training steps solve a data-domain problem.
- Do not treat variants of one synthetic voice as speaker diversity.
- Do not generate a large corpus before G1 explicitly unlocks it.
- Do not let train/test share derivatives of the same base audio.
- Do not select hardware before sustained Fold4 measurements.
- Do not count virtual RAM as physical RAM.
- Do not split grandmother/personal presentation into separate products.
- Do not make the senior UI dense or menu-heavy.
- Do not spawn a fresh Claude CLI process per request.
- Do not allow LLM output to bypass guarded safety/device boundaries.
- Do not rely on chat memory when Git differs.

## Immediate restart instruction

> Read this handoff and `AIHUB_MASTER_EXECUTION_CHECKLIST.md`, verify the branch HEAD, and continue from the highest-priority dependency-satisfied gate. At this checkpoint the immediate work is Fold4 evidence (G2.8/G3.29/G3.30/G3.33), remaining G1 human QC, and the pinned real v4 replay prerequisite for G2.5. Do not begin later product/sensing backlog to avoid these blockers.
