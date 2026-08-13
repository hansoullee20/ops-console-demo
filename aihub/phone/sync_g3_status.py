#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = ROOT / "AIHUB_MASTER_EXECUTION_CHECKLIST.md"
HANDOFF = ROOT / "AIHUB_HANDOFF.md"
EVIDENCE = ROOT / "aihub" / "phone" / "G3_31_VOICE_TRUST_STATE_EVIDENCE.md"


def replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one source block, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


old_g32 = '''- [ ] **G3.2 Core voice events implemented** — P0  
  `wake.candidate/detected/rejected`, listening, transcript, intent, confirmation, command accepted/failed.
  Partial evidence: commit `a1aa9c3` emits/validates wake detected, listening started, transcript final and assistant result events on the Android/bridge path; commit `f2a41f6` emits replay-safe command accepted/completed/failed events from the guarded boundary. Keep unchecked until remaining wake candidate/rejection, transcript/listening failure, intent and confirmation producers exist.
'''
new_g32 = '''- [x] **G3.2 Core voice events implemented** — P0
  `wake.candidate/detected/rejected`, listening, transcript, intent, confirmation, command accepted/failed.
  Evidence: commit `88fd83f` makes the live Android recognizer lifecycle observable with wake candidate/detected/rejected, listening start/stop/failure and transcript partial/final/failure events in a bounded volatile ledger. Commit `2f2f892` adds exact bridge-side intent requested/resolved/failed and explicit two-turn confirmation requested/accepted/rejected producers while refusing to pretend a physical device action executed without an adapter. Contract run `31692595222` and APK run `31692595239` are green. Durable record: `aihub/phone/G3_2_CORE_VOICE_EVIDENCE.md`.
'''

old_g331 = '''- [ ] **G3.31 Microphone-off/offline/error states tested** — P0.
'''
new_g331 = '''- [x] **G3.31 Microphone-off/offline/error states tested** — P0.
  Evidence: commits through `a33117f` add explicit READY/LISTENING/THINKING/MIC_OFF/OFFLINE_DEGRADED/ERROR_RECOVERY policy and wire it into the live Android activity. MIC_OFF destroys and nulls `SpeechRecognizer`, disables manual talk and automatic wake, and permission-gates re-enable; bridge failures enter a retryable degraded state; recognizer/TTS failures enter recovery. State plus live-source integration tests pass in run `31693447185`; APK build `31693447195` is green. Durable record: `aihub/phone/G3_31_VOICE_TRUST_STATE_EVIDENCE.md`. Fold4 endurance remains separate under G3.29/G3.30/G3.33.
'''

replace_exact(CHECKLIST, old_g32, new_g32)
replace_exact(CHECKLIST, old_g331, new_g331)

checkpoint_marker = '''- G3.6/G3.9/G3.10 are closed: commit `1434c3f` adds one senior/personal schema with guarded caregiver preferences and five independent consent records; run `31682851423` and APK run `31682851417` are green. Android UI/delivery remains open.
'''
checkpoint_add = checkpoint_marker + '''- G3.2 is closed: `88fd83f` completes the live recognizer lifecycle and `2f2f892` adds real intent/confirmation producers; contract run `31692595222` and APK run `31692595239` are green.
- G3.31 is closed at the software-contract level: live MIC_OFF destroys microphone access, offline bridge and recovery states are explicit, integration run `31693447185` and APK run `31693447195` are green. Physical Fold4 reliability remains G3.29/G3.30/G3.33.
'''
replace_exact(CHECKLIST, checkpoint_marker, checkpoint_add)

handoff_marker = "## Active continuation log — 2026-08-13\n"
handoff_insert = handoff_marker + '''\n### G3.2/G3.31 voice lifecycle and trust-state continuation — completed\n\n- Starting parent checkpoint was evidence commit `0dc65b1`; branch already contained `88fd83f` when work resumed. That commit completed the recognizer-owned wake/listening/transcript lifecycle and bounded volatile event ledger.\n- Commit `2f2f892` adds exact intent and explicit confirmation event contracts/producers on the real transcript bridge. Recognized TV/AC/phone-finder requests require a second spoken confirmation and remain explicitly unexecuted when no physical adapter exists. Contract run `31692595222` and APK run `31692595239` are green. G3.2 is closed; physical integrations remain separate gates.\n- G3.31 audit found the old “wake word off” control was not MIC_OFF because manual talk could still activate the recognizer. The live activity now has explicit READY/LISTENING/THINKING/MIC_OFF/OFFLINE_DEGRADED/ERROR_RECOVERY states; MIC_OFF destroys/nulls SpeechRecognizer and blocks both manual and automatic input; bridge and recognizer/TTS failures render degraded/recovery states.\n- A first live-source integration test run `31693382427` failed because the test over-specified the bridge-state assignment spelling; the implementation was correct. The assertion was corrected to verify the actual degraded-result flow. Final integration run `31693447185` and APK run `31693447195` both pass. G3.31 is closed at the software-contract level. G3.29, G3.30 and G3.33 remain open for physical Fold4 endurance/full-cycle evidence.\n- Durable records: `aihub/phone/G3_2_CORE_VOICE_EVIDENCE.md` and `aihub/phone/G3_31_VOICE_TRUST_STATE_EVIDENCE.md`.\n\n'''
replace_exact(HANDOFF, handoff_marker, handoff_insert)

old_evidence = "- Integration-contract run: `31693382427` (must be green before G3.31 is marked complete)."
new_evidence = "- Final integration-contract run `31693447185` passed after correcting one over-specific test assertion; APK build `31693447195` also passed. The earlier run `31693382427` is retained as failed-test evidence, not product-failure evidence."
replace_exact(EVIDENCE, old_evidence, new_evidence)

old_status = "Status: implemented; close only after the integration-contract CI run is green."
new_status = "Status: COMPLETE — software trust-state contract verified in CI; physical Fold4 endurance remains separate."
replace_exact(EVIDENCE, old_status, new_status)

print("Synchronized G3.2 and G3.31 status/evidence.")
