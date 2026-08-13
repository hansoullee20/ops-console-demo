#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HANDOFF = ROOT / "AIHUB_HANDOFF.md"
PLAN = ROOT / "AIHUB_MASTER_EXECUTION_CHECKLIST.md"
HEAD = "ec05901b7279ff69ab7d298d36cd9e1000b322f1"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


old_checkpoint = "> **CURRENT CHECKPOINT:** Okja v3 remains rejected as a deployable model. Reusable evaluator, benchmark contract, diagnostic ring buffer and deterministic replay harness now exist. Real LiveKit replay run `31669141305` and alternative openWakeWord replay run `31670716561` used the exact same pinned v3 classifier/audio SHAs and were deterministic over three repeats per threshold. Their engine-specific scores differ, which is compatibility evidence rather than a changed v3 quality verdict. The alternative-runtime portion of G2.5 is complete; G2.5 stays open only until a pinned real v4 classifier replays the identical audio SHA. G1 audit/validation work also closed G1.1–G1.4, G1.6–G1.9 and G1.11; the v4 scaling gate remains blocked only by G1.5 and G1.10. Existing Android SpeechRecognizer remains the working control/fallback.\n"
new_checkpoint = f'''> **CURRENT CHECKPOINT:** Branch checkpoint before this documentation refresh is `{HEAD}`. G3.2, G3.31 and G3.32 are closed with green contract/APK evidence: the live voice lifecycle is observable through intent/confirmation, MIC_OFF and degraded/recovery states are explicit, and the localhost bridge binds before lazy/retryable Claude client initialization. Existing Android SpeechRecognizer remains the working control/fallback. The immediate blockers are physical Fold4 evidence (G2.8, G3.29, G3.30, G3.33), remaining human TTS listening/QC (G1.10; Chatterbox G1.5 remains rejected), and a pinned real v4 classifier for G2.5. Do not treat later UI, device, sensing or pilot gates as current blockers.\n\n## NEXT ACTION / EXECUTION ORDER\n\n1. Run one structured Fold4 session that captures at least 20 accepted wake attempts/full cycles and the target-device latency evidence needed by G2.8/G3.30, while observing sustained-idle behavior for G3.29.\n2. Leave the instrumented app running toward the 24-hour G3.33 stability smoke; preserve logs before changing code.\n3. If device evidence exposes failures, fix only the evidenced failure and rerun the affected gate.\n4. Complete remaining G1 human listening disposition and produce/replay the pinned real v4 classifier before unlocking large generation or model bake-off work.\n5. Only after those blockers are resolved, resume G3 product UI and physical TV/AC/phone-finder integration work.\n\n**DO NOT START YET:** later G3 UI expansion, G4 pilot claims, or G5/G6 sensing work merely because their checklist items are open. They remain planned work, not the immediate critical path.\n'''
replace_once(HANDOFF, old_checkpoint, new_checkpoint)
replace_once(HANDOFF, "## Active continuation log — 2026-08-13\n", "## Historical continuation/evidence log — 2026-08-13\n\nThe sections below are retained as implementation history and evidence. They are **not** the current execution queue; use NEXT ACTION above and the canonical checklist for current priority.\n")

plan_marker = "- Product direction is one Okja app/firmware with senior/personal profiles.\n"
plan_insert = plan_marker + '''\n### Immediate execution order\n\n1. **Fold4 evidence first:** combine G2.8, G3.29 and G3.30 in one structured target-device session where practical; then continue the same instrumented build toward G3.33.\n2. **Evidence-driven repair only:** if the Fold4 run fails, fix the observed failure before starting unrelated feature work.\n3. **Finish blocked wake/data prerequisites:** complete G1.10 human listening disposition (G1.5 remains rejected unless new evidence changes it) and obtain the pinned real v4 classifier required by G2.5 before large generation/model bake-off proceeds.\n4. **Then resume product integration:** G3 senior/personal UI and real TV/AC/phone-finder flows follow after the current reliability/data blockers are resolved.\n\n**Planning guard:** unchecked later G3/G4/G5/G6 items are backlog unless their prerequisite gate is satisfied. Do not jump to sensing/pilot work to avoid a blocked physical or human-evidence gate.\n'''
replace_once(PLAN, plan_marker, plan_insert)
print("Refreshed handoff checkpoint and master-plan execution order.")
