# Okja / 옥자 — Current Project Plan

**Status:** ACTIVE  
**Updated:** 2026-08-13 KST  
**Branch:** `aihub-voice-test`  
**Canonical gate/evidence tracker:** `AIHUB_MASTER_EXECUTION_CHECKLIST.md`  
**Restart handoff:** `AIHUB_HANDOFF.md`

This document defines the **current execution order**. The master checklist remains authoritative for gate definitions, checkbox state and evidence. If the checklist's older bottom section titled `Current P0 queue` conflicts with this plan, **this file supersedes that legacy queue** until the checklist section is rewritten.

## 1. Current objective

Reach a trustworthy Fold4 daily-use Okja baseline before expanding product scope.

The immediate problem is no longer missing core voice contracts. G3.2, G3.31 and G3.32 are complete at the software/evidence level. The next decisions must come from target-device measurements and the remaining wake/data prerequisites.

## 2. Critical path

### Phase A — Fold4 evidence

Run one structured target-device session that combines as much evidence as practical:

1. **G2.8 latency:** at least 20 accepted wake attempts in one valid session; generate strict P50/P95 report using `aihub/wakeword/V4_ANDROID_LATENCY_MEASUREMENT.md`.
2. **G3.30 full-cycle reliability:** at least 20 wake → listen → transcript/intent → response cycles, recording failures rather than restarting around them.
3. **G3.29 sustained idle:** observe the instrumented app under sustained idle and preserve resource/reliability evidence.
4. **G3.33 stability:** continue the same instrumented build toward a 24-hour app stability smoke.

Where a physical gate fails, preserve logs first, fix only the evidenced failure, and rerun the affected gate.

### Phase B — finish blocked G1/G2 wake prerequisites

1. Complete **G1.10** human listening disposition for every remaining admitted smoke phrase/voice combination, including Kokoro English.
2. Keep failed Chatterbox Korean positives quarantined; **G1.5 remains failed/open** unless genuinely new evidence supports a replacement/approved path.
3. Do not unlock **G1.14 large generation** until G1's explicit prerequisites pass.
4. Produce a small pinned real **v4 classifier** only after the data gate permits it.
5. Replay the same pinned real audio SHA through v4 to close the remaining portion of **G2.5**.
6. Then establish TEST A/B/C/D and run v3/v4/alternative KWS on the same benchmark before model selection.

### Phase C — resume G3 product integration

After the current Fold4/data blockers are resolved, continue product v1 work in dependency order:

1. senior accessibility settings consumed by Android runtime;
2. senior/personal visual design and Android screens;
3. real TV, AC and phone-finder adapters and flows;
4. wellness check-in and non-diagnostic symptom journal UI;
5. night/ambient and emergency full-screen behavior;
6. family ETA/notification UI and caregiver dashboard;
7. notification-priority policy.

Do not claim a gate complete from contract code alone when its DoD requires UI, physical device behavior or human verification.

### Phase D — limited senior pilot

Only after G3 passes on the Fold4:

- senior usability;
- real-home wake behavior;
- family calling/phone finder;
- TV/AC actions;
- wellness snooze/decline;
- consent/reversibility;
- night-mode behavior;
- 119 guidance/legal assumptions;
- understandable retention/privacy controls.

### Phase E — presence, safety sensing and hardware cost-down

G5/G6 sensing and G7 hardware selection remain later phases. Do not use them to bypass unresolved G1–G4 evidence.

## 3. Current completed foundation

The detailed evidence remains in the master checklist. Important completed foundations include:

- G0 project reproducibility foundation;
- v4 runtime locks, provenance, QC, leakage and deterministic script/split infrastructure;
- benchmark schema, marker, diagnostic ring buffer, evaluator and statistical reporting;
- deterministic v3 and openWakeWord replay infrastructure;
- versioned event envelope;
- core recognizer/intent/confirmation lifecycle;
- idempotent device-command boundary and capability flags;
- guarded emergency state machine with automatic 119 disabled;
- shared senior/personal profile and independent consent schema;
- care/family event contracts;
- MIC_OFF/offline/error trust states;
- lazy/resilient bridge startup.

## 4. Explicit blockers

### Human / physical

- G1.10 human pronunciation/listening QC;
- G2.8 Fold4 latency measurement;
- G2.12 real-human wake set;
- G2.13 fixed household benchmark;
- G2.19+ long-duration household/device-hour evidence;
- G3.29/G3.30/G3.33 Fold4 reliability;
- later G4 usability/pilot evidence.

### Model/data

- G1.5 Chatterbox Korean positive path remains rejected/open;
- G1.14 large generation remains locked;
- G2.5 waits for pinned real v4 replay;
- G2.10/G2.11/G2.14–G2.17 require the actual v4/shared benchmark stage.

### UI/device integration

- G3.7 and G3.12–G3.28 remain product implementation work after the immediate evidence blockers;
- physical TV/AC/phone-finder behavior remains unverified despite the completed command contract.

## 5. Do not start yet

Do not start the following merely because code work is available:

- G4 pilot claims before G3 Fold4 reliability passes;
- G5 door/PIR/mmWave presence integration;
- G6 fall/night-sensing model work;
- automatic emergency-services behavior;
- final cheap-hardware selection or BOM cost-down.

## 6. Evidence discipline

For every gate:

1. verify branch/head;
2. verify relevant CI or target-device run;
3. preserve failure evidence;
4. record commit/run/report/device identity;
5. change `[ ]` to `[x]` only when the exact DoD is satisfied.

Never substitute “code exists” for physical, human, legal or runtime evidence required by the gate.

## 7. Immediate session procedure

At the start of a new work session:

1. read `AIHUB_HANDOFF.md`;
2. read this plan;
3. read `AIHUB_MASTER_EXECUTION_CHECKLIST.md` for exact gate/evidence state;
4. verify the current Git head and recent CI;
5. select the first dependency-satisfied item on the critical path above.

## 8. Current next action

**Next user/device action:** run the structured Fold4 evidence session for G2.8 + G3.30 and begin/continue G3.29/G3.33 observation using the instrumented build. Preserve the resulting event ledger/logs before any code changes.
