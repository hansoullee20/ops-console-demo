# Okja v4 Android wake-latency measurement

This procedure produces G2.8 P50/P95 evidence from the target Android device.
It does not claim a latency result until a real device session passes the
minimum sample gate.

## Metric definition

The diagnostic detector records one monotonic timeline per candidate:

- `vad_onset_monotonic_ms`: start of the first 20 ms frame that crosses the
  local voice-activity threshold;
- `segment_end_monotonic_ms`: end of the captured wake segment after trailing
  silence or the segment cap;
- `decision_monotonic_ms`: time immediately after MFCC/DTW scoring;
- `wake_latency_ms`: VAD onset to detector decision;
- `post_segment_processing_ms`: segment end to detector decision.

All timestamps use `android.os.SystemClock.elapsedRealtime`. Wall-clock time is
not used, so clock or timezone changes cannot alter a session result. The app
also records device fingerprint, Android SDK, app version, session ID and the
SHA-256 of the exact six enrolled template files.

## Target-device procedure

1. Install the debug APK built from the commit under test on the target Fold4.
2. Enroll all six prompts, start local detection once, and leave that detector
   session running for the entire measurement. Restarting detection creates a
   new session ID.
3. Make at least 20 intentional attempts that the detector accepts. Record the
   attempted/missed count separately; this latency report covers accepted
   decisions and does not replace recall measurement.
4. Pull only the metadata ledger; the WAV diagnostics are not required:

   ```bash
   adb exec-out run-as com.soul.aihub \
     cat files/wake_diagnostics/wake_diagnostic_events.jsonl \
     > wake_diagnostic_events.jsonl
   ```

5. From the repository root, validate the latest session and write the report:

   ```bash
   python aihub/wakeword/v4_android_latency_report.py \
     --events wake_diagnostic_events.jsonl \
     --min-samples 20 \
     --require-complete \
     --output wake_latency_report.json
   ```

Use `--session-id` only when intentionally reporting an earlier session. The
tool fails closed on inconsistent timestamp arithmetic, mixed devices, mixed
app versions, mixed template hashes or fewer than the required accepted events.

## Evidence required to close G2.8

- `measurement_complete` is `true` with at least 20 accepted events;
- `target_device` identifies the Fold4 and a single Android fingerprint;
- app version and template-set SHA-256 are singular and non-empty;
- `wake_latency_ms.p50` and `wake_latency_ms.p95` are present;
- the report, source commit and APK workflow run are recorded in the checklist
  and handoff.

The report reads event metadata only. Retain or delete diagnostic WAV files
according to the applicable consent and retention decision; they are not part
of the latency calculation.
