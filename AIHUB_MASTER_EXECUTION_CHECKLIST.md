# Okja / 옥자 — Master Execution Checklist

**Status:** ACTIVE / canonical execution tracker  
**Branch:** `aihub-voice-test`  
**Created:** 2026-08-12 KST  
**Git source of truth:** repository state wins over chat memory.  
**Companion docs:** `AIHUB_HANDOFF.md`, `AIHUB_V4_TEST_PLAN.md`, `AIHUB_UI_INFORMATION_ARCHITECTURE.md`, `AIHUB_AMBIENT_CARE_RESEARCH.md`

---

## 0. How this checklist is used

This file is the project's **execution contract**. Work should move item-by-item and gate-by-gate.

### Checkbox rules

A checkbox may be marked `[x]` only when its **Definition of Done (DoD)** is satisfied and evidence exists.

Acceptable evidence:

- Git commit SHA / PR;
- GitHub Actions run ID + conclusion;
- benchmark/report artifact;
- reproducible command + output;
- target-device test record;
- human listening/usability review record;
- hardware test log;
- legal/privacy decision record where required.

**Never close an item only because code was written.** A buildable feature that has not been tested remains incomplete.

### Priority tags

- **P0** — blocks the next release gate.
- **P1** — high-value work that can proceed in parallel.
- **P2** — follows v1 foundation.
- **P3** — safety/advanced sensing; no premature shipping.

### Owner lanes

- **AI-ENG** — implementation/debugging/documentation suitable for ChatGPT/Claude collaboration.
- **HUMAN** — listening, consent, real-life use, subjective UX, physical deployment.
- **HW** — sensors/device measurements.
- **LEGAL** — privacy/regulatory/119 assumptions.

### Current checkpoint

- Working branch exists and is canonical: `aihub-voice-test`.
- Android SpeechRecognizer → local bridge → persistent Claude Agent SDK → Android TTS path works and remains fallback/control.
- LiveKit v3 is rejected as deployable wakeword; do not threshold-tune it.
- MeloTTS Korean is approved for initial v4 data; smoke generation, provenance, WAV QC, split and leakage checks are green. Chatterbox remains a secondary source with quarantined pronunciation failures.
- G2 evaluator, recording contract, privacy-first candidate ring buffer and deterministic replay harness exist and have green CI evidence.
- Real LiveKit v3 replay run `31669141305` and openWakeWord replay run `31670716561` are deterministic over three repeats at thresholds 0.50 and 0.06 on the exact same model/audio SHAs. G2.5 remains open only for the pinned real v4 replay.
- G1.12/G1.13 are closed: commit `7b37c8b` freezes 425 unique bilingual scripts with pre-generation train/validation assignments; evaluator run `31677969571`, data-smoke run `31677969581` and MeloTTS run `31677969589` are green.
- Product direction is one Okja app/firmware with senior/personal profiles.

---

# RELEASE GATE G0 — Project foundation is reproducible

**Goal:** Any new ChatGPT/Claude session can restart correctly from Git without relying on chat history.

- [x] **G0.1 Canonical repo/branch documented** — P0 / AI-ENG  
  DoD: repository, branch, project paths documented in Git.  
  Evidence: `AIHUB_HANDOFF.md`.

- [x] **G0.2 Working voice control path documented** — P0 / AI-ENG  
  DoD: known-good Android SpeechRecognizer → bridge → persistent Claude → TTS path and fallback policy documented.

- [x] **G0.3 Failed v2/v3 model conclusions frozen** — P0 / AI-ENG  
  DoD: exact evaluation numbers and “do not integrate/tune” guidance are in Git.

- [x] **G0.4 Three-track execution model documented** — P0 / AI-ENG  
  DoD: Wake/Data, Test/Evaluation, Product UI/UX tracks documented.

- [x] **G0.5 Research direction documented** — P1 / AI-ENG  
  DoD: ambient care/sensing research and product implications stored in Git.

**G0 PASS:** YES.

---

# RELEASE GATE G1 — v4 data generation is reproducible and safe to scale

**Goal:** Tiny Korean + English real-TTS corpus passes generation, provenance, QC, split and leakage checks before any large generation.

## G1-A. Environment reproducibility

- [x] **G1.1 Pin Chatterbox implementation exactly** — P0 / AI-ENG
  DoD: tested package version or Git commit is pinned; API used by generator matches installed implementation; environment is reproducible from clean CI.  
  Evidence: `v4_sources_manifest.yaml` and `okja-v4-data-smoke.yml` pin `chatterbox-tts==0.1.7` and document the tested `from_pretrained(device=device)` API. Clean run `31612771436` installed that package and generated/uploaded six real Chatterbox WAVs.

- [x] **G1.2 Pin all v4 TTS/runtime dependencies** — P0 / AI-ENG
  DoD: Kokoro, Chatterbox, audio libs and critical transitive versions are bounded or locked.  
  Evidence: commit `ab96ecce5380b77f27654ff487df0c30f2e643cd` adds platform/Python-specific locks containing 110 Kokoro, 122 Chatterbox and 170 MeloTTS exact pins, pins Python `3.11.15`/`3.9.25` and pip `26.2.1`/`26.0.1`, runs `pip check`, and requires sorted `pip freeze` equality before synthesis. Clean locked runs `31676094058` and `31676094114` passed dependency verification, generation, manifest validation, WAV QC, leakage and artifact upload for all three engines.

- [x] **G1.3 Record generator provenance per clip** — P0 / AI-ENG
  DoD: manifest includes engine, engine version/commit, voice, language, script/text ID, seed, source/license, base/parent ID, file SHA-256.
  Evidence: commit `844134b9aa363fe25e2e10265b9b61ed2cff3ea1` makes `source_license` mandatory and adds fail-closed manifest validation for required provenance, enum, SHA, numeric and finite-value constraints. Unit run `31671445691` passes 35 tests. Real smoke runs `31671445654` and `31671445689` validate the Kokoro, Chatterbox and MeloTTS manifests before leakage checks and artifact upload.

## G1-B. Smoke-corpus integrity

- [x] **G1.4 English Kokoro smoke succeeds** — P0 / AI-ENG
  DoD: actual WAVs generated, normalized, manifest emitted, QC passes.  
  Evidence: run `31612771436` generated four real Kokoro `0.9.4` English WAVs; all four passed mono/16 kHz WAV QC and were uploaded with raw/split/QC manifests. Run `31671445654` repeats the clean path with the enforced manifest contract.

- [ ] **G1.5 Korean Chatterbox smoke succeeds** — P0 / AI-ENG  
  DoD: actual Korean WAVs generated with correct `옥자` pronunciation and manifest/QC passes.  
  Blocker evidence: run `31612771436` generated six real Chatterbox `0.1.7` WAVs and passed automated QC, but human review in `V4_PRONUNCIATION_QC.md` rejected the Chatterbox positive pronunciation/naturalness. Keep unchecked; do not admit the failed positives to training.

- [x] **G1.6 Smoke holdout policy is valid** — P0 / AI-ENG
  DoD: either >=3 voices allow meaningful train/val/test speaker holdout OR smoke-only checker explicitly reports speaker holdout `not_evaluable` without weakening full-corpus rules.
  Evidence: `v4_dataset_tools.py` assigns speaker/engine test splits only from explicit holdout roles and prints absent smoke holdouts as `not_evaluable`; run `31671445654` exercises that policy for the one-voice Kokoro/Chatterbox smoke, while MeloTTS run `31671445689` exercises an explicit `test_engine` holdout.

- [x] **G1.7 Failed CI always preserves diagnostics** — P0 / AI-ENG
  DoD: WAVs/manifests/reports upload with `if: always()` or equivalent even after QC/leakage failure.
  Evidence: commit `c9793ea59bbd69a87cf65c1228107e020ca8c3f4` adds opt-in controlled WAV corruption after generation/split assignment. Dispatch runs `31676607342` and `31676609594` failed at `audio-qc --fail-on-qc` as intended, while every engine still captured its resolved environment, wrote a summary and uploaded generated audio plus `manifest_qc.csv` and a failure marker. Downloaded artifacts contained exactly one `unreadable:EOFError` row each (`smoke_kokoro_01`, `smoke_chatterbox_01`, `smoke_melotts_01`) with the remaining 3/5/3 rows passing. Normal push runs `31676594090` and `31676594032` remained green.

- [x] **G1.8 WAV QC gate passes** — P0 / AI-ENG
  DoD: decode, mono/16 kHz normalization, finite samples, plausible duration, silence, clipping, DC offset/loudness and duplicate checks are reported.
  Evidence: `v4_dataset_tools.py` checks every listed condition and fails the job on QC errors. Runs `31671445654` and `31671445689` pass the gate for all 14 real smoke WAVs across Kokoro, Chatterbox and MeloTTS.

- [x] **G1.9 Leakage gate passes** — P0 / AI-ENG
  DoD: parent/base derivatives, normalized text/template, augmentation lineage and held-out speaker/engine policies show zero forbidden leakage.
  Evidence: the checker rejects base/template cross-split leakage, duplicate audio hashes and held-out engine/voice overlap. Runs `31671445654` and `31671445689` pass after deterministic split assignment and manifest validation.

- [ ] **G1.10 Human pronunciation QC passes** — P0 / HUMAN  
  DoD: at least one person listens to every smoke phrase/voice combination; mispronunciations are quarantined and documented.
  Partial evidence: all MeloTTS Korean smoke clips were approved in `V4_MELOTTS_HUMAN_QC.md`; failed Chatterbox positives are quarantined in `V4_PRONUNCIATION_QC.md`. Keep unchecked until every remaining intended smoke phrase/voice combination, including Kokoro English, has an explicit listening disposition.

## G1-C. Corpus scaling gate

- [x] **G1.11 Second independent Korean TTS source approved** — P1 / AI-ENG
  DoD: model/weights/output license and Korean quality are verified; provenance added to manifest.
  Evidence: `v4_sources_manifest.yaml` pins MeloTTS code commit `209145371cff8fc3bd60d7be902ea69cbdb7965a`, model revision `0207e5adfc90129a51b6b03d89be6d84360ed323`, model-file SHAs and MIT terms; clean run `31615755020` plus `V4_MELOTTS_HUMAN_QC.md` approved it for initial v4 data and engine-holdout use.

- [x] **G1.12 Owned conversation script library finalized** — P1 / AI-ENG
  DoD: positives, general negatives, hard negatives, mention-context, device-playback negatives, truncated/near-miss cases have deterministic IDs.
  Evidence: commit `7b37c8b` adds all seven scenarios in Korean and English and commits a generator-identical `v4_scripts.csv` with 425 unique content-derived IDs and 425 unique `(language, normalized_text)` keys. Evaluator run `31677969571` is green.

- [x] **G1.13 Split is assigned before augmentation** — P0 / AI-ENG
  DoD: parent sample group cannot cross train/val/test after augmentation.
  Evidence: commit `7b37c8b` freezes 345 train and 80 validation assignments at script-planning time, preserves valid preassigned splits, rejects holdout conflicts, and fails parent/template or normalized-text cross-split leakage. Data-smoke run `31677969581` and MeloTTS holdout run `31677969589` are green.

- [ ] **G1.14 Large generation is explicitly unlocked** — P0  
  DoD: G1.1–G1.10 are all `[x]`. No exception.

**G1 PASS:** NO — BLOCKED.

---

# RELEASE GATE G2 — Wakeword evaluation architecture is trustworthy

**Goal:** Every wake model is judged on the same real-world benchmark; no model is selected from synthetic validation alone.

## G2-A. Benchmark recorder and annotations

- [x] **G2.1 24-hour household recording spec implemented** — P0 / AI-ENG
  DoD: file naming, device/room metadata, timestamps, firmware/model SHA and consent/retention fields are defined and validated.
  Evidence: `v4_benchmark_schema.json` + `v4_benchmark_contract.py` require and validate recording/device/room IDs, timezone-aware start time, duration, WAV basename, audio SHA-256, firmware/app/model provenance, consent, retention and TEST_D immutability/training exclusion; tests pass after commit `3779753d49d8e02f110062a55d72eaf2e3ac8f1a` in verification run `31652866104`.

- [x] **G2.2 Intentional-wake marker exists** — P0 / AI-ENG
  DoD: intentional wake attempts can be timestamped with speaker, phrase, distance, voice level and environment.
  Evidence: `v4_benchmark_contract.py mark-wake` writes evaluator-compatible truth JSONL with recording-relative timestamp, speaker, phrase/language, distance, direction, voice level, room/background/condition and mention-context; unit test `test_marker_writes_evaluator_compatible_truth_row` passes in run `31652866104`.

- [x] **G2.3 Candidate ring-buffer logger exists** — P0 / AI-ENG
  DoD: near-threshold/accepted candidate events save short diagnostic clips and scores without persisting all-day raw audio by default.
  Evidence: `aihub/wakeword/v4_ring_buffer_logger.py` + `test_v4_ring_buffer_logger.py`; evaluator CI run #7 / `31651625304` passed; Android `WakeDiagnosticRingBuffer.java` is wired into the live `AudioRecord` loop and accepted/near-threshold decision path by commit `e8ffd3978a42b767f01c7c0df5ebe6f6e563a354`; pre-commit debug APK build passed in run `31652333689`.

- [x] **G2.4 Manual missed-wake capture exists** — P1 / AI-ENG
  DoD: user can mark a missed activation and preserve the relevant buffered clip.
  Evidence: commit `e8ffd3978a42b767f01c7c0df5ebe6f6e563a354` adds the active-detector-only `방금 옥자를 놓쳤어 · 진단 저장` control backed by `markManualMiss()`; ring-buffer unit tests cover manual-miss persistence; run `31652333689` built and uploaded the wired debug APK artifact. Target-device behavioral validation remains a separate later gate.

- [ ] **G2.5 Offline deterministic replay exists** — P0 / AI-ENG  
  DoD: identical recording can be replayed through v3/v4/other engines with pinned model/threshold/version metadata.
  Partial evidence: commit `0d6f7188fc15d05a31045944b9d4d240877d3148` adds the LiveKit v3 adapter and artifact-pinned replay workflow; unit run `31669141480` passes 25 tests. Real replay run `31669141305` verified pinned model SHA `3cff1a6c...` and audio SHA `a9551898...`, then produced identical results over three repeats at thresholds 0.50 and 0.06. Commit `4c59e9ea612190ec9bd80ccc7ac8562450f5577a` adds the openWakeWord `0.6.0` compatibility adapter with pinned official feature-model hashes and initialization seed; unit run `31670716607` passes 32 tests and real replay run `31670716561` is 3/3 deterministic at both thresholds on the same classifier/audio SHAs. See `aihub/wakeword/V3_REAL_REPLAY_EVIDENCE.md` and `aihub/wakeword/OPENWAKEWORD_REAL_REPLAY_EVIDENCE.md`. Keep unchecked until a pinned real v4 classifier replays the same audio SHA.

## G2-B. Metrics and reports

- [x] **G2.6 Threshold sweep report exists** — P0 / AI-ENG
  DoD: threshold vs recall/FRR/FPR-hour is automatically generated.
  Evidence: `v4_eval.py` emits deterministic threshold sweeps with recall, miss/FRR, FPPH and false-alarms/day; CLI report smoke and unit tests passed in run `31653692637` after commit `7a8a5f033a846de262fd2d3fd48fa2765d7d7821`.

- [x] **G2.7 Condition breakdown exists** — P1 / AI-ENG
  DoD: metrics by phrase, speaker, distance, direction, TV/noise, self-TTS, day/night are reported.
  Evidence: commit `7a8a5f033a846de262fd2d3fd48fa2765d7d7821` adds benchmark-contract metadata and evaluator groups for phrase, speaker, distance bucket, direction, background/TV-noise, voice level, self-TTS and day/night, including `speaker_id`/`room_id` compatibility; tests passed in run `31653692637`.

- [ ] **G2.8 Latency metrics exist** — P1 / AI-ENG  
  DoD: P50/P95 wake latency measured on target Android device.

- [x] **G2.9 Statistical confidence is reported** — P1 / AI-ENG
  DoD: negative listening hours and confidence bounds accompany false-trigger rates; zero observed events is never presented as zero true rate.
  Evidence: `v4_eval.py` reports negative exposure hours, Wilson recall CI and Poisson false-positive rate CI; the zero-FP unit test verifies a non-zero 95% upper rate bound, and all evaluator tests passed in run `31653692637`.

## G2-C. Evaluation sets

- [ ] **G2.10 TEST A held-out synthetic speakers complete** — P0.
- [ ] **G2.11 TEST B held-out TTS engine complete** — P0.
- [ ] **G2.12 TEST C real-human wake set complete** — P0 / HUMAN.
- [ ] **G2.13 TEST D fixed household benchmark established** — P0 / HUMAN.  
  Rule: TEST D never becomes training data.

## G2-D. Model bake-off

- [ ] **G2.14 v3 baseline evaluator runs on new benchmark** — P1 / AI-ENG.
- [ ] **G2.15 v4 candidate evaluated on identical benchmark** — P0 / AI-ENG.
- [ ] **G2.16 At least one alternative fully local/open KWS evaluated** — P0 / AI-ENG.  
  Candidates: openWakeWord, sherpa-onnx, microWakeWord or another legally compatible local engine.
  Partial evidence: openWakeWord `0.6.0` compatibility replay run `31670716561` passed with pinned feature-model hashes, seed and 3/3 deterministic results on the shared positive WAV. This is not yet a full benchmark evaluation; keep unchecked until the shared positive, hard-negative and long-negative corpus produces recall/FRR, FPPH and latency/resource evidence. See `aihub/wakeword/OPENWAKEWORD_REAL_REPLAY_EVIDENCE.md`.

- [ ] **G2.17 Two-stage architecture prototype evaluated** — P1 / AI-ENG  
  DoD: Stage A high-recall KWS → Stage B high-precision phrase verifier; benchmark demonstrates whether cascade improves false-trigger economics.

- [ ] **G2.18 Commercial/reference engine may be benchmarked only as a control** — P2  
  Rule: AccessKey/commercial dependency does not silently become final architecture if fully-free/local requirement remains active.

## G2-E. Release evidence

- [ ] **G2.19 24 h household smoke completed** — P0.
- [ ] **G2.20 100 h multi-condition negative benchmark completed** — P1.
- [ ] **G2.21 300+ negative device-hours release gate completed/planned** — P1 / HUMAN.  
  Parallel devices may be used to accumulate device-hours faster.

**G2 PASS:** NO.

---

# RELEASE GATE G3 — Product v1 is an integrated daily-use Okja

**Goal:** One Android product with senior/personal profiles, stable voice interaction, device actions and family communication.

## G3-A. Backend/UI contract

- [ ] **G3.1 Versioned event envelope implemented** — P0 / AI-ENG  
  Required fields: schema version, event ID, timestamps, device/profile/session/correlation IDs, source, severity, privacy/retention.

- [ ] **G3.2 Core voice events implemented** — P0  
  `wake.candidate/detected/rejected`, listening, transcript, intent, confirmation, command accepted/failed.

- [ ] **G3.3 Device command contract implemented and idempotent** — P0  
  TV, AC, phone finder now; washer capability reserved/disabled until integration exists.

- [ ] **G3.4 Care/family event contract implemented** — P1  
  Wellness, symptom record, arrival/departure, ETA, notification, emergency escalation events.

- [ ] **G3.5 LLM cannot directly bypass guarded emergency state machine** — P0.

## G3-B. Profile/config schema

- [ ] **G3.6 One shared profile schema supports senior + personal modes** — P0.
- [ ] **G3.7 Senior accessibility settings implemented** — P1  
  Large type, solar+lunar date, quiet hours/night mode, simple quick actions.
- [ ] **G3.8 Device capability flags implemented** — P1  
  TV=true, AC=true, washer future/hidden until connected.
- [ ] **G3.9 Family/caregiver notification preferences implemented** — P1.
- [ ] **G3.10 Privacy/health/camera/benchmark consents are separate fields** — P0.

## G3-C. Senior UI

- [x] **G3.11 Senior information architecture defined** — P1.
- [ ] **G3.12 Senior Figma design system created** — P1 / AI-ENG + HUMAN.
- [ ] **G3.13 Senior Android screen implemented from design** — P1 / AI-ENG.
- [ ] **G3.14 Large date + solar/lunar runtime conversion verified** — P1.
- [ ] **G3.15 TV flow implemented** — P1  
  Continue watching, recommendation, favorite channels, simple TV-on path.
- [ ] **G3.16 AC control implemented** — P1.
- [ ] **G3.17 Phone finder implemented for senior** — P1.
- [ ] **G3.18 Wellness check-in implemented** — P1.
- [ ] **G3.19 Symptom journal implemented as record, not diagnosis** — P1.
- [ ] **G3.20 Night/screen-off ambient behavior implemented** — P1.
- [ ] **G3.21 Emergency full-screen UI implemented** — P1.
- [ ] **G3.22 Family ETA banner implemented** — P1  
  Example: family member is on the way + approximate ETA.

## G3-D. Personal/caregiver UI

- [x] **G3.23 Personal information architecture defined** — P1.
- [ ] **G3.24 Personal/caregiver Figma design created** — P1.
- [ ] **G3.25 Today/schedule/tasks/home-state dashboard implemented** — P1.
- [ ] **G3.26 One-tap “going to Grandma’s” action implemented** — P1.
- [ ] **G3.27 Grandma home/away activity timeline implemented** — P1.
- [ ] **G3.28 Notification priority policy implemented** — P1  
  Normal activity does not spam; unusual absence/night departure/fall escalate appropriately.

## G3-E. Target-device reliability

- [ ] **G3.29 Fold4 sustained idle measurement completed** — P0 / HUMAN.
- [ ] **G3.30 >=20 wake attempts + full cycles measured** — P0 / HUMAN.
- [ ] **G3.31 Microphone-off/offline/error states tested** — P0.
- [ ] **G3.32 Bridge startup made lazy/resilient** — P1.
- [ ] **G3.33 24 h app stability smoke completed** — P0 / HUMAN.

**G3 PASS:** NO.

---

# RELEASE GATE G4 — Senior household pilot is safe enough for limited use

**Goal:** Useful real-home pilot without pretending Okja is a medical device.

- [ ] **G4.1 Senior usability test with real older adult completed** — P0 / HUMAN.
- [ ] **G4.2 Wake recall/false-trigger behavior acceptable in actual home** — P0.
- [ ] **G4.3 Family calling + phone finder verified end-to-end** — P0.
- [ ] **G4.4 TV/AC actions verified on real devices** — P1.
- [ ] **G4.5 Wellness prompts can be snoozed/declined** — P0.
- [ ] **G4.6 Health journal sharing policy is consented and reversible** — P0 / LEGAL + HUMAN.
- [ ] **G4.7 Night mode does not disturb sleep; wake remains available** — P0.
- [ ] **G4.8 119 안심콜 onboarding guidance implemented** — P1.
- [ ] **G4.9 No undocumented automatic 119 integration claim** — P0 / LEGAL.
- [ ] **G4.10 Data-retention/privacy dashboard or settings are understandable** — P1.

**G4 PASS:** NO.

---

# RELEASE GATE G5 — Presence and daily-activity care v2

**Goal:** Arrival/departure and inactivity signals are useful with privacy-first sensing.

## G5-A. Presence backbone

- [ ] **G5.1 Door/contact sensor prototype integrated** — P2 / HW.
- [ ] **G5.2 PIR or mmWave presence prototype integrated** — P2 / HW.
- [ ] **G5.3 Arrival/departure fusion state machine implemented** — P2 / AI-ENG.
- [ ] **G5.4 Sensor-offline is distinct from “no activity”** — P0.
- [ ] **G5.5 User can correct wrong arrival/departure event** — P1.

## G5-B. Household identity / unknown presence

- [ ] **G5.6 Presence classes defined: senior / known household / unknown** — P2.
- [ ] **G5.7 Camera identity is optional secondary evidence, not basic requirement** — P0.
- [ ] **G5.8 Local silhouette/pose/gait experiment evaluated** — P2 / AI-ENG + HUMAN.
- [ ] **G5.9 BLE/phone + voice + door/presence fusion evaluated** — P2.
- [ ] **G5.10 Unknown-person alert requires persistence/multi-signal confirmation** — P1.
- [ ] **G5.11 Raw continuous video is not stored by default** — P0.

## G5-C. Personalized activity baseline

- [ ] **G5.12 Initial baseline period defined** — P2.
- [ ] **G5.13 Transparent rolling-quantile/EWMA baseline implemented first** — P2.
- [ ] **G5.14 Away/asleep/device-off exceptions implemented** — P0.
- [ ] **G5.15 Inactivity alerts validated for caregiver usefulness vs spam** — P1 / HUMAN.

**G5 PASS:** NO.

---

# RELEASE GATE G6 — Night sensing and fall/emergency intelligence

**Goal:** Safety features are validated as uncertain-assistance systems, never presented as infallible detection.

## G6-A. Night sensing

- [ ] **G6.1 Privacy-first night sensor selected/prototyped** — P3 / HW  
  Prefer mmWave/radar/door/presence over bedroom camera.
- [ ] **G6.2 Night waking estimate validated** — P3.
- [ ] **G6.3 Bathroom-transition estimate validated without bathroom camera** — P0.
- [ ] **G6.4 UI uses “estimated” wording where signal is inferential** — P0.

## G6-B. Fall detection research

- [ ] **G6.5 Public/actor fall + large ADL hard-negative dataset assembled legally** — P3.
- [ ] **G6.6 No frail older adult is asked to stage dangerous falls** — P0.
- [ ] **G6.7 Temporal sequence model benchmarked** — P3.
- [ ] **G6.8 Radar/presence candidate evaluated** — P3.
- [ ] **G6.9 Optional local pose fusion evaluated in common areas only** — P3.
- [ ] **G6.10 Fall model emits `fall.suspected`, not unquestionable `fall.occurred`** — P0.

## G6-C. Emergency escalation

- [ ] **G6.11 Detect → ask → wait → escalate state machine implemented** — P0.
- [ ] **G6.12 Senior “괜찮아” dismissal path tested** — P0.
- [ ] **G6.13 No-response path tested** — P0.
- [ ] **G6.14 Multiple-family urgent notification tested** — P0.
- [ ] **G6.15 Emergency telephony behavior tested on target hardware** — P0.
- [ ] **G6.16 Korean privacy/regulatory review completed before external pilot** — P0 / LEGAL.
- [ ] **G6.17 NFA/119 integration assumptions verified** — P0 / LEGAL.
- [ ] **G6.18 Automatic 119 behavior remains disabled until validated/authorized** — P0.

**G6 PASS:** NO.

---

# RELEASE GATE G7 — Hardware selection and cost-down

**Goal:** Select inexpensive standalone hardware only from measured requirements.

- [ ] **G7.1 Sustained CPU/RAM/battery/thermal measurements captured on Fold4** — P1 / HUMAN.
- [ ] **G7.2 Stage-A + Stage-B wake resource envelope measured** — P1.
- [ ] **G7.3 STT/bridge/TTS peak and steady-state resources measured** — P1.
- [ ] **G7.4 Camera/presence/radar resource additions measured separately** — P2.
- [ ] **G7.5 Minimum RAM/storage/SoC envelope derived from data** — P1.
- [ ] **G7.6 Candidate cheap Android hardware shortlist benchmarked** — P2.
- [ ] **G7.7 Final BOM/cost target reviewed only after reliability gates** — P2.

**G7 PASS:** NO.

---

# Cross-cutting requirements — never waived silently

## Privacy / data governance

- [ ] Separate essential-product, health/symptom, caregiver-sharing, camera, and research/benchmark consent.
- [ ] Always-on raw audio is not durably stored by default.
- [ ] Wake ring buffer is volatile unless a candidate/miss is intentionally captured.
- [ ] Entryway raw video storage is off by default.
- [ ] Bedroom camera is avoided; bathroom camera is prohibited in product design.
- [ ] Health information is treated as sensitive; no medical diagnosis claim from wellness journal.
- [ ] Every retained dataset has provenance, purpose, retention class and deletion path.

## Reliability / observability

- [ ] Every critical event has schema version and correlation ID.
- [ ] Every model decision/report records model SHA/version and threshold.
- [ ] Device actions return success/failure, not optimistic UI-only confirmation.
- [ ] Sensor unavailable/offline is surfaced explicitly.
- [ ] Failed CI preserves evidence.
- [ ] Reproduction commands/environment are stored with benchmark results.

## UX / accessibility

- [ ] Senior primary actions use very large touch targets and text.
- [ ] Critical actions are never tiny-icon-only controls.
- [ ] Listening/mic-off/offline state is always unambiguous.
- [ ] Senior flows minimize choices; one obvious action per step where possible.
- [ ] Night display can go essentially black while local wake remains active.
- [ ] Emergency UI is deterministic, large, and visually distinct.

---

# Current P0 queue — execute in this order

1. [ ] **P0-01 Fix/pin Korean Chatterbox smoke environment.**
2. [ ] **P0-02 Fix smoke holdout semantics / add enough voices.**
3. [ ] **P0-03 Upload diagnostics/artifacts even when smoke job fails.**
4. [ ] **P0-04 Re-run v4 smoke until Korean + English generation/QC/leakage gates are valid.**
5. [ ] **P0-05 Human-listen to smoke WAVs and quarantine pronunciation failures.**
6. [ ] **P0-06 Implement 24 h benchmark recorder/annotation schema + ring buffer candidate logger.**
7. [ ] **P0-07 Implement offline replay + threshold/FPR-hour/recall report.**
8. [ ] **P0-08 Freeze event/profile contracts and begin Android integration against them.**
9. [ ] **P0-09 Create Figma senior/personal design system and validate accessibility.**
10. [ ] **P0-10 Establish real-human wake set + first household benchmark before declaring v4 success.**

---

# Weekly / session operating procedure

At the start of every work session:

1. Read `AIHUB_HANDOFF.md`.
2. Read this checklist.
3. Verify current Git branch HEAD.
4. Verify any active/recent GitHub Actions runs before claiming status.
5. Select the highest-priority unchecked item whose dependencies are satisfied.
6. Implement/test it.
7. Add evidence to Git/report.
8. Only then change `[ ]` → `[x]`.
9. If a test fails, record the failure and next blocker; do not hide it by moving to a later gate.

At every meaningful milestone:

- update this checklist;
- update `AIHUB_HANDOFF.md` if architecture/restart instructions changed;
- keep experimental data/results linked to exact Git/model versions.

---

# Definition of project milestones

### M1 — Data foundation ready
G1 passes.

### M2 — Wakeword objectively comparable
G2 passes through at least TEST A/B/C and first household benchmark; a candidate architecture is selected by evidence.

### M3 — Daily-use Okja v1
G3 passes on Fold4.

### M4 — Limited senior home pilot
G4 passes.

### M5 — Presence/care pilot
G5 passes.

### M6 — Safety prototype
G6 validated in controlled pilot; no automatic emergency claim without legal/telephony verification.

### M7 — Cost-down hardware selection
G7 passes after resource measurements.

---

## Rule of thumb

**We do not advance because a feature is impressive. We advance because the preceding gate is measurably satisfied.**
