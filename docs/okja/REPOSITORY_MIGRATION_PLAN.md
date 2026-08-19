# Project Okja — Repository Migration Plan

## Decision
Project Okja should become a dedicated repository. `ops-console-demo` is an operations-console codebase (Python application, database migrations, routers, tests and deployment workflows) and is not an appropriate permanent root for the Android voice assistant.

At the time of this audit, the connected GitHub account exposes `hansoullee20/ops-console-demo`, while a repository named `project-okja` is not present through the connected installation. Code search in `ops-console-demo` did not find `Okja`, `AudioRecord`, or `SpeechRecognizer`. Therefore do **not** destructively reorganize or delete the existing repository in an attempt to extract code that is not visible there.

## Migration rule
Preserve history and evidence first. No deletion from `ops-console-demo` until the actual Android source location is identified and the new repository is validated.

## Proposed target repository
`project-okja`

Recommended structure:

```text
project-okja/
├── README.md
├── LICENSE
├── .gitignore
├── .github/
│   ├── workflows/
│   └── ISSUE_TEMPLATE/
├── docs/
│   ├── architecture/
│   │   ├── voice-pipeline.md
│   │   ├── adr-001-single-mic-owner.md
│   │   └── adr-002-asr-selection.md
│   ├── research/
│   │   └── android-voice-ecosystem-2026-08.md
│   ├── experiments/
│   │   └── mode-f.md
│   └── product/
│       └── interaction-states.md
├── android/
│   ├── app/
│   ├── core-audio/
│   ├── voice-wake/
│   ├── voice-vad/
│   ├── voice-asr/
│   ├── intent-router/
│   └── device-adapters/
├── benchmarks/
│   ├── corpus/
│   ├── results/
│   └── scripts/
├── models/
│   └── README.md
└── tools/
```

Large model binaries and private voice recordings should not be committed directly. Store manifests/checksums/download instructions; keep personal recordings outside public Git history.

## Module boundaries
- `core-audio`: sole AudioRecord owner, PCM bus, ring buffer, timing/diagnostics.
- `voice-wake`: pure PCM-in -> wake-event-out interface.
- `voice-vad`: pure PCM-in -> speech-state-out interface.
- `voice-asr`: buffered/live PCM-in -> transcript events; Android and sherpa adapters.
- `intent-router`: transcript -> deterministic command or AI fallback request.
- `device-adapters`: Home Assistant and direct-device implementations.
- `app`: lifecycle, foreground service, UI, permissions and dependency wiring.

No wake/ASR module may instantiate AudioRecord.

## Branch strategy
- `main`: always buildable.
- short-lived `feat/*`, `experiment/*`, `docs/*` branches.
- experiments must end in either an ADR decision or explicit rejection note.
- avoid permanent `develop` branch unless multiple concurrent maintainers make it necessary.

## Documentation system
Every architecture-changing experiment should leave four artifacts:
1. hypothesis;
2. device/test conditions;
3. raw/summary result;
4. decision and consequence.

Use ADRs for decisions that future work should not casually reverse.

## Immediate execution sequence
1. Capture the 2026 Android/open-source research in version control. **Done on the migration-planning branch.**
2. Capture this repository migration plan. **Done.**
3. Locate the actual Android/Okja source repository or working tree. **Blocked: not present in the currently connected `ops-console-demo` tree/search.**
4. Create/authorize `project-okja` or expose the repository that already contains the Android project.
5. Copy/move Android source without rewriting behavior.
6. Establish baseline build/test on the new repository.
7. Add `core-audio` abstraction and tests.
8. Preserve old handoff as a named experiment, then implement Mode F.
9. Add sherpa benchmark adapter in parallel.
10. Select production ASR from Fold4 measurements and record ADR.
11. Only after migration verification, remove stale Okja material from any old repository.

## Definition of repository cleanup complete
- one canonical Okja repository;
- Android project builds from a clean checkout;
- architecture/research/experiment docs are versioned;
- no secrets, model blobs or private recordings in Git;
- CI runs unit tests and Android build/lint;
- benchmark schema/results are reproducible;
- old repositories contain either no Okja code or a clear pointer/archive note;
- architecture decisions are represented by ADRs rather than chat history.