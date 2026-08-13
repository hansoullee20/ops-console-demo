#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = ROOT / "AIHUB_MASTER_EXECUTION_CHECKLIST.md"
HANDOFF = ROOT / "AIHUB_HANDOFF.md"


def replace_exact(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one source block, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_exact(
    CHECKLIST,
    "- [ ] **G3.32 Bridge startup made lazy/resilient** — P1.\n",
    "- [x] **G3.32 Bridge startup made lazy/resilient** — P1.\n"
    "  Evidence: commits `f401413`, `0221af5` and `8ec1977` add a lazy per-profile agent pool and move Claude client initialization behind the already-bound localhost request handler. Failed initialization is not cached, concurrent first use initializes once, profiles recover independently, and a source-level CI guard prevents direct eager SDK context entry from returning. Runs `31693869837` and `31693994203` are green. Durable record: `aihub/phone/G3_32_BRIDGE_STARTUP_EVIDENCE.md`.\n",
)

marker = "- G3.31 is closed at the software-contract level: live MIC_OFF destroys microphone access, offline bridge and recovery states are explicit, integration run `31693447185` and APK run `31693447195` are green. Physical Fold4 reliability remains G3.29/G3.30/G3.33.\n"
replace_exact(
    CHECKLIST,
    marker,
    marker + "- G3.32 is closed: localhost binds before Claude client initialization; clients are lazy, per-profile and retryable after initialization failure. Runs `31693869837` and `31693994203` are green.\n",
)

handoff_marker = "### G3.2/G3.31 voice lifecycle and trust-state continuation — completed\n"
handoff_insert = '''### G3.32 lazy/resilient bridge startup — completed\n\n- The known startup defect was confirmed: both persistent Claude clients were entered before TCP `127.0.0.1:8765` opened, so an SDK initialization timeout could make the bridge itself unavailable.\n- `okja_lazy_agent_pool.py` now keeps profile factories inert until first use. The bridge binds localhost first; only a request that actually needs the agent calls `pool.get(profile)`. Intent/confirmation responses can remain available without agent initialization.\n- Per-profile locks deduplicate concurrent first startup. Failed initialization is not cached, so a later request retries; grandma/personal initialization is independent.\n- Run `31693869837` passed lazy-pool recovery tests. Final run `31693994203` also passed a live-source guard that rejects reintroduction of eager `ClaudeSDKClient` context entry before server startup.\n- G3.32 is closed. Physical Fold4 endurance/full-cycle gates G3.29/G3.30/G3.33 remain open. Durable record: `aihub/phone/G3_32_BRIDGE_STARTUP_EVIDENCE.md`.\n\n'''
replace_exact(HANDOFF, handoff_marker, handoff_insert + handoff_marker)

print("Synchronized G3.32 status/evidence.")
