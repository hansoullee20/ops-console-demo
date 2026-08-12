# Okja / 옥자 — Execution Governance

**Status:** ACTIVE  
**Applies to:** `AIHUB_MASTER_EXECUTION_CHECKLIST.md` and all Okja release-gate planning  
**Principle:** the checklist is a living execution system, not a frozen project plan.

## 1. Constant addition and review

The master checklist is **subject to continuous addition, deletion, reprioritization, decomposition, merging, and review** as new evidence appears.

New research, user feedback, benchmark results, hardware constraints, privacy/safety findings, implementation discoveries, or product decisions may change the checklist at any time.

A previously correct priority is not protected merely because it was written first.

## 2. Priorities are hypotheses

P0/P1/P2/P3 are current execution priorities, not permanent labels.

- Promote an item when it becomes a blocker or materially reduces project risk.
- Demote an item when evidence shows it can wait.
- Split an item when its Definition of Done is too broad to verify cleanly.
- Merge duplicate work when two items share the same evidence/gate.
- Remove obsolete work explicitly rather than leaving stale unchecked tasks forever.

Every priority change should be driven by current evidence and recorded in Git when material.

## 3. Release gates are stable goals, implementation paths may change

Release-gate intent should remain comparatively stable: reproducibility, trustworthy evaluation, integrated daily use, safe senior pilot, privacy-preserving sensing, and validated emergency behavior.

The implementation chosen to satisfy a gate may change freely. No model, library, sensor, vendor, UI layout, or architecture is sacred.

If a better implementation satisfies the same gate with stronger evidence, replace the old path rather than completing obsolete work for checklist purity.

## 4. Review triggers

Perform a checklist/priority review whenever any of the following occurs:

1. a P0 item completes or fails;
2. a benchmark produces materially new evidence;
3. a new research result changes an architectural assumption;
4. a hardware/device test reveals a constraint;
5. real-user feedback changes UX priorities;
6. privacy, safety, legal, or emergency-policy findings change risk;
7. a new high-value feature is added;
8. an implementation is substantially easier/harder than expected;
9. before starting a large/expensive data generation or training run;
10. before declaring any release gate passed.

## 5. Checklist item lifecycle

Use these meanings:

- `[ ]` — open / not yet proven.
- `[x]` — Definition of Done satisfied with evidence.
- `BLOCKED` — cannot proceed until a named dependency is resolved.
- `DEFERRED` — still useful but intentionally moved out of the current gate.
- `REPLACED` — superseded by another item/approach; preserve the reason.
- `DROPPED` — intentionally removed because it no longer serves the product.

Completed work can be reopened if later evidence invalidates the original Definition of Done.

## 6. Evidence over schedule

Dates and week estimates are planning aids only. They must not cause weak evidence to be accepted.

Conversely, if automation, ChatGPT/Claude collaboration, reuse of existing components, or parallel test devices allow a gate to finish faster, the schedule should compress rather than waiting for an old timeline.

## 7. Continuous backlog intake

When a new product idea is proposed:

1. capture it immediately;
2. classify it as current-gate, parallel, later, or research-only;
3. identify dependencies and safety/privacy implications;
4. give it a measurable Definition of Done before implementation if it becomes active;
5. assign priority only relative to the current project bottleneck.

Ideas do not need to be rejected merely because they were absent from the original plan.

## 8. Mandatory review question

Before choosing the next task, ask:

> Given everything we know now, is this still the highest-leverage next action toward the nearest release gate?

If not, change the checklist and priority order first.

## 9. Source-of-truth rule

Git remains the canonical record. ChatGPT and Claude should read the current branch and the master checklist/governance docs before making status claims or choosing work. Chat memory may propose additions but must not override the repository state without an explicit update.
