# Okja G2 Implementation Status

**Status:** active evidence ledger; master checklist remains canonical and must be reconciled separately.
**Branch:** `aihub-voice-test`
**Updated:** 2026-08-13 KST

This file records implementation evidence without claiming release-gate closure beyond what is actually proven.

## Implemented and tested

### G2.1 household benchmark capture contract

Implemented:
- `aihub/wakeword/v4_benchmark_schema.json`
- `aihub/wakeword/v4_benchmark_contract.py`
- `aihub/wakeword/AIHUB_V4_HOUSEHOLD_BENCHMARK_SPEC.md`

The contract defines WAV naming, device/room/recording IDs, timestamps/duration, WAV SHA-256, firmware/app/model provenance, consent and retention fields. TEST D is mechanically constrained to `training_eligible=false`, `immutable=true`, and `retention_class=benchmark_fixed`.

### G2.2 intentional wake marker

`v4_benchmark_contract.py mark-wake` emits and validates timestamped intentional wake rows with phrase, language, speaker, room, background, condition, and optional distance/direction/voice-level metadata.

### G2.6 / G2.7 / G2.9 evaluator foundation

Implemented:
- `aihub/wakeword/v4_eval.py`
- `aihub/wakeword/test_v4_eval.py`

The evaluator performs one-to-one event matching, counts duplicate/unmatched detections as false positives, and reports recall/miss, FPPH, false alarms/day, latency, group breakdowns and statistical confidence.

### G2.3 candidate ring-buffer logger

Reference implementation:
- `aihub/wakeword/v4_ring_buffer_logger.py`

Android helper:
- `aihub/app/src/main/java/com/soul/aihub/WakeDiagnosticRingBuffer.java`

Behavior:
- continuous PCM stays in memory;
- default diagnostic window is 3 s pre-roll + 2 s post-roll;
- only explicit candidate/manual-miss captures are persisted;
- candidate metadata records score, threshold and accepted/rejected state;
- saved WAVs carry SHA-256 and JSONL event metadata.

The Android helper is wired into the active `AudioRecord` loop and accepted or
near-threshold scoring path. Continuous audio stays volatile; only explicit
diagnostic windows are persisted.

### G2.4 manual missed-wake capture

Both reference and Android helpers expose a manual-miss capture primitive. The
active-detector-only Android control invokes it and preserves the buffered
window.

G2.3/G2.4 implementation evidence is commit
`e8ffd3978a42b767f01c7c0df5ebe6f6e563a354` and APK run `31652333689`.

### CI evidence

Evaluator run `31677969571` passed the 43-test suite after the script/split
gate work. The latest Android ring-buffer wiring build evidence remains APK run
`31652333689`; newer latency instrumentation must receive its own clean build
run before it is considered ready for physical measurement.

## Implemented as reference/helper but not yet closed

### G2.5 deterministic offline replay

LiveKit v3 and openWakeWord adapters replay the same pinned audio/model inputs
deterministically. G2.5 stays open until a pinned real v4 classifier replays the
same input.

### G2.8 target-device latency metrics

Implementation in progress adds monotonic VAD-onset, segment-end and decision
timestamps to Android candidate metadata, on-screen accepted-event P50/P95,
exact enrolled-template SHA-256 identity, and the strict metadata-only
`v4_android_latency_report.py` report. See
`V4_ANDROID_LATENCY_MEASUREMENT.md`.

**Not closed yet:** APK/unit CI establishes instrumentation readiness only.
G2.8 requires at least 20 accepted attempts measured on the target Fold4 in a
single detector session.

## Still open / next highest-value work

1. Obtain clean evaluator and APK CI for the G2.8 instrumentation.
2. Run the documented >=20-attempt Fold4 latency session and preserve its JSON report.
3. Replay a pinned real v4 classifier over the existing fixed audio to close G2.5.
4. Run v3 baseline and future candidates against identical TEST A/B/C/D material.
5. Keep Android/physical checklist items open until device evidence exists.
