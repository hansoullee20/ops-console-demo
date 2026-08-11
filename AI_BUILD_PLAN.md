# OPS Console — AI Build Plan

Repository: `hansoullee20/ops-console-demo`

Live demo: `https://hansoullee20.github.io/ops-console-demo/`

## 0. Current status

This repository currently contains a public mock-data demo for a university cleaning-staff operations console.

Current UI baseline:
- Korean UI
- Main tabs: 운영 / 근태 / 휴가 / 직원 / 문서
- 운영: Daily / Weekly / Monthly
- Employee names open a profile drawer
- Profile quick actions: 근태 / 휴가 / 대체 배정 / 문서 / 메모
- About 18 fictional employees are used for demo data
- Mobile and desktop layouts exist
- Current AI assistant is mock/demo only

IMPORTANT: user feedback on the current UI is still pending.
Do not redesign the UI or add speculative features before that feedback arrives unless explicitly instructed.

---

# 1. Target architecture

## Work PC = canonical host

The work computer will become the single authoritative host.

Target stack:
- FastAPI backend
- SQLite single source of truth
- deterministic business rules in Python/SQL
- uploaded source files and documents
- backup/snapshot system
- audit log
- controlled local business tool layer / MCP

Do not maintain separate SQLite copies on phone and PC.

## Phone = PWA client

The phone should use the same application and same backend.

Desktop default:
- Weekly operations view

Mobile default:
- Daily operations view
- today’s exceptions
- employee lookup/profile
- leave/sick leave handling
- substitute staffing
- notes
- document/photo upload

## AI

Claude Code / Claude Dispatch and Codex / ChatGPT Remote will run on or connect to the work PC.

Both AI systems must use the SAME controlled business tool layer.

AI must not receive unrestricted SQL write access.
AI must not directly edit or delete raw fingerprint punch records.

Read flow:
- AI → controlled read tool → deterministic backend → result

Write flow:
- AI proposal → explicit user confirmation → deterministic backend commit → audit log

---

# 2. Non-negotiable data rules

1. SQLite is the canonical business source, never browser localStorage.
2. Attendance must enforce unique `(employee_id, work_date)`.
3. Preserve every raw fingerprint punch event.
4. Never delete a punch merely because it looks duplicated.
5. Short-gap punch detection is a review flag only.
6. 3 or 4 punches can be legitimate because the terminal can contain 출 / 외 / 퇴 / 복 semantics.
7. Substitute assignment must never overwrite normal attendance.
8. Leave duration must use the site work calendar, not naïve calendar-day subtraction.
9. Annual leave balance must be year-specific.
10. Imports require preview, source preservation, snapshot and rollback.
11. Do not use destructive DELETE→INSERT for routine attendance corrections.
12. Manual or AI-assisted changes need audit history.
13. Handle overlapping leave explicitly.
14. Handle attendance before hire date explicitly.
15. Handle missing leave days explicitly.
16. Handle half-day leave explicitly.
17. Handle site-specific non-working days and schedule exceptions explicitly.

---

# 3. Fingerprint source constraints

The real fingerprint terminal currently exports monthly legacy `.XLS` files.

Therefore:
- never pretend fingerprint attendance is live unless a same-day import exists
- always expose the last fingerprint import/sync time
- leave, substitution, notes and document state entered in the app may be live even while fingerprint data is stale

Known behavior from the real XLS investigation:
- a whole-site zero-punch day can occur
- this must not automatically become an absence for every employee
- terminal registration slot != active employee roster
- terminal slot ↔ employee mapping must exist in the database
- close-in-time punches may be flagged as repeated-punch candidates, but raw events remain untouched

---

# 4. Security rules

This application may eventually contain employee and medical/leave information.

Rules:
- production backend must not be directly exposed to the public internet
- no public SQLite endpoint
- no public MCP endpoint
- no secrets in frontend code or git
- no unrestricted shell presented as a business tool
- minimize employee data sent to hosted models
- do not dump the whole DB to Claude or GPT
- raw fingerprint source data is not AI-writable
- remote access must use authenticated HTTPS / employer-approved private access
- workplace policy overrides convenience

---

# 5. Development rules for all agents

Before changing code:
1. inspect the repository
2. identify conflicts with this plan
3. briefly state implementation plan

While changing code:
- preserve current UI unless the task explicitly requires UI changes
- do not rewrite unrelated code
- do not add payroll, inventory, analytics, project management or unrelated modules
- do not silently make destructive migrations
- migrations must be idempotent and backed up
- add tests for meaningful backend/rules changes
- do not claim a feature works unless actually tested
- if a dependency/CLI is missing, fail gracefully
- keep commits small and descriptive

At the end of every phase report:
- files changed
- tests run
- exact test results
- remaining risks
- next recommended step

---

# 6. Agent roles

Preferred split:

## Claude Code
Primary implementation agent.
Good fit for:
- backend implementation
- local file/document workflows
- business tool layer / MCP
- Claude Dispatch integration
- operational workflow implementation

## Codex
Primary adversarial reviewer and test/fix agent.
Good fit for:
- code review
- regression testing
- import edge cases
- backend diagnostics
- test failures
- architecture verification
- maintenance through ChatGPT Remote

Either agent may implement, but the other should review important phases.
Do not let the same agent be the only verifier of its own work.

---

# 7. Phase plan

## PHASE 0 — UI freeze while feedback is pending

Current UI is a testable baseline.

Until user feedback arrives:
- do not redesign
- do not add speculative features
- only fix proven UI bugs
- preserve the current visual interaction model

If user feedback arrives, insert a small `Phase 0.5` before backend migration and apply only agreed UI changes.

---

## PHASE 1 — Production-capable backend skeleton

Goal: add backend/data foundation without changing current demo behavior.

Create a structure roughly equivalent to:

```text
app/
  main.py
  db.py
  models/
  schemas/
  services/
  rules/
  routers/
  migrations/
  tests/

data/
uploads/
backups/
frontend/
```

Implement:
- FastAPI
- SQLite initialization
- migration/version mechanism
- health endpoint

Minimum tables:
- employees
- attendance_days
- punch_events
- leave_requests
- replacement_assignments
- notes
- documents
- site_calendar
- audit_log
- import_runs

Critical constraints:
- foreign keys enabled
- timestamps
- status fields where needed
- unique employee/work_date attendance row
- raw punch records modeled as immutable source events

Tests:
- DB initialization
- migrations re-run safely
- unique attendance constraint
- FK behavior
- raw source record protections where implemented

STOP after Phase 1.
Do not connect frontend to API yet.
Do not add AI yet.
Do not add remote access yet.

---

## PHASE 2 — Replace duplicated mock JS data with backend API

Goal: same UI, one backend source.

Seed the SAME fictional 18-person dataset into SQLite.

Implement APIs for:
- employee list/profile
- Daily / Weekly / Monthly operations data
- attendance detail
- leave cases
- replacement status
- notes
- document metadata

Requirements:
- frontend uses backend data
- no separate parallel employee dataset in JS
- no localStorage as canonical storage
- loading states
- visible network/API error states
- profile name-click behavior preserved
- profile quick actions preserved
- desktop Weekly default
- mobile Daily default

Tests:
- API tests
- consistency across views
- frontend smoke-test strategy

STOP after Phase 2.
Do not add XLS import yet.
Do not add AI yet.

---

## PHASE 3 — Fingerprint XLS import pipeline

Goal: safe deterministic import of real terminal exports.

Import flow:
1. upload source XLS
2. preserve original file
3. parse
4. preview
5. show slot mapping/errors/findings
6. create snapshot
7. explicit confirmation
8. apply import
9. record import_run
10. allow rollback

Rules:
- every source punch becomes a punch_event
- never delete raw punch events
- derive attendance_days separately
- reimport should be idempotent where possible
- configurable repeated-punch review threshold
- empirical starting point may be 20 minutes
- repeated-punch logic flags only

Support:
- terminal slot → employee mapping
- unmapped slots
- inactive employees
- 0 / 1 / 2 / 3 / 4+ punches
- 출 / 외 / 퇴 / 복-compatible sequences
- whole-site zero-punch candidate days
- site calendar exceptions
- approved leave + punch conflict
- attendance before hire
- rollback after import
- partial import failure

UI:
`지문 XLS 가져오기 → 미리보기 → 확인 → 적용`

Always display:
`지문 데이터 기준: <last imported timestamp/date>`

Add fixture-based regression tests.

AI must not decide attendance status in this phase.

---

## PHASE 4 — Real leave / sick leave / replacement workflows

Leave support:
- annual leave
- half-day leave
- sick leave
- evidence/document linkage
- approval state
- return-to-work state
- site-work-calendar day calculation
- yearly leave balance
- overlapping leave detection

Important rule:
If requested sick-leave dates exceed medical-certificate support, create a finding.
Never silently modify either period.

Replacement support:
- vacancy
- candidate
- assignment
- site/zone
- date/shift
- status
- who replaced whom
- audit history

Never overwrite normal attendance when assigning a substitute.

Connect existing profile quick actions to real backend workflows.

---

## PHASE 5 — PWA for work PC + phone

Goal: same app, same backend, installable on phone.

Implement:
- manifest
- service worker
- installability
- responsive navigation
- mobile Daily default
- desktop Weekly default
- offline indicator

Mobile priority:
- today’s exceptions
- employee search/profile
- leave/sick case status
- replacement assignment
- notes
- photo/document upload

Security:
- cache application shell/static assets only by default
- do not cache sensitive API payloads by default
- offline business writes disabled initially
- show `오프라인` clearly

Do not expose the backend publicly yet.

---

## PHASE 6 — Secure phone ↔ work-PC access

DESIGN FIRST. Do not deploy until explicitly approved.

Evaluate at least:
A. Cloudflare Tunnel + Access
B. employer-approved VPN/private-access equivalent

For each document:
- authentication
- TLS
- revoke procedure
- lost-phone scenario
- work-PC sleep/offline behavior
- firewall exposure
- backend bind address
- logging/audit implications
- cost
- employer-policy implications

Default rule:
FastAPI and SQLite must never be directly internet-exposed.

After explicit approval, implement only the approved option.

---

## PHASE 7 — Controlled local business tool layer / MCP

Goal: Claude and Codex can operate against the same safe tools.

READ tools:
- get_current_view
- get_employee
- get_attendance
- get_leave
- get_issues
- get_replacement_status
- get_document_info

WRITE proposal tools:
- update_attendance
- assign_replacement
- create_note

READ tools may execute directly.

WRITE tools must return a proposed action, not commit immediately.

Proposed action should include:
- action type
- target
- before state
- proposed after state
- reason
- provider/source
- confirmation token

Commit endpoint must:
- validate again
- apply deterministic rules
- write audit record
- record provider/session where available

Never expose generic SQL as an AI business tool.
Never allow AI to edit/delete raw punch_events.
Keep transport localhost-only or stdio unless explicitly redesigned later.

---

## PHASE 8A — Claude Code / Dispatch

Goal: from phone, Claude Dispatch can delegate work to the work PC using controlled tools.

Representative tasks:
- 오늘 확인할 것 정리해
- 김가람 병가 문제 확인해
- 오늘 결원 누구야
- 대체인력 후보 찾아
- 오늘 업무보고 초안 만들어

Rules:
- business tools first, raw DB access only for development/debugging where appropriate
- minimum employee context sent to model
- no unrestricted DB writes
- write proposal requires app confirmation
- log tool activity where practical
- handle work PC offline gracefully
- use subscription-authenticated Claude Code where available; do not silently fall back to paid API keys

Document exact setup and failure modes.

---

## PHASE 8B — Codex / ChatGPT Remote

Goal: use Codex Remote primarily for software maintenance and diagnostics on the work PC.

Priority use cases:
- code maintenance
- XLS import debugging
- test failures
- backend diagnostics
- automation improvements
- safe operational reads through the same business tools

Rules:
- no bypass of business tool layer for employee-data writes
- source files and credentials remain on host
- document setup, permissions and failure behavior
- use subscription-authenticated Codex where supported; do not silently fall back to paid API keys

---

## PHASE 9 — Production readiness review

Do not add features.

Audit:
- data loss
- concurrency
- backup/restore
- migration rollback
- audit integrity
- XLS idempotency
- stale fingerprint-data UX
- authentication
- lost phone
- work-PC reboot
- work-PC sleep
- Claude unavailable
- Codex unavailable
- remote-access outage
- document upload failure
- invalid dates
- year rollover
- employee termination/reactivation
- leave balance rollover
- malformed imported files

Rank findings:
- P0 data loss/security
- P1 operational correctness
- P2 usability
- P3 cleanup

Fix P0/P1 only unless explicitly asked otherwise.

End with a GO / NO-GO recommendation.

---

# 8. Cross-review protocol

After Claude Code implements a phase, ask Codex:

> Inspect the actual repository and tests. Do not trust the implementation claim. Compare the requested phase in AI_BUILD_PLAN.md with the code. Run relevant tests. Fix only defects you can substantiate. Report blocking defects, fixes, test results, remaining risks, and whether the next phase is safe.

After Codex implements a phase, ask Claude Code the same thing in reverse.

---

# 9. Current instruction

Unless the user explicitly says otherwise:

**Start with Phase 1 only.**

Do not continue automatically into Phase 2.
At the end of Phase 1, stop and report results for review.
