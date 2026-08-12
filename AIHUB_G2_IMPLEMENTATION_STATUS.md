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

### CI evidence

`Okja v4 Evaluator Tests` run `31651625304` passed after adding benchmark-contract and privacy-ring-buffer unit coverage. The immediately preceding run `31651564822` failed only because a test incorrectly expected Python's `TemporaryDirectory` root itself not to exist; the assertion was corrected to verify that the logger creates no durable audio/event files before an explicit capture.

## Implemented as reference/helper but not yet closed

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

**Not closed yet:** the Android helper is not yet wired into the live wake detector's scoring loop, so target-device candidate capture has not been demonstrated.

### G2.4 manual missed-wake capture

Both reference and Android helpers expose a manual-miss capture primitive.

**Not closed yet:** no live Android UI/control currently invokes it, and no target-device capture has been demonstrated.

## Still open / next highest-value work

1. Wire the Android ring buffer to the active microphone stream and near-threshold/accepted candidate scoring point without destabilizing the existing wake fallback/control path.
2. Add a manual missed-wake action in the diagnostic UI.
3. Verify Android build and then target-device capture behavior.
4. Implement G2.5 deterministic offline model replay that emits the detection JSONL contract.
5. Run v3 baseline and future candidates against identical TEST A/B/C/D material.
6. Reconcile `AIHUB_MASTER_EXECUTION_CHECKLIST.md` with this evidence; do not mark Android/physical items complete until device evidence exists.
