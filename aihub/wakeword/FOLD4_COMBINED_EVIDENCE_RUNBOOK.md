# Okja Fold4 combined evidence runbook

This runbook combines the currently blocked target-device work without changing privacy policy or pretending software tests are physical evidence.

## Gates covered

- **G2.8** — target Android P50/P95 wake latency, minimum 20 accepted wake attempts.
- **G3.29** — sustained-idle target-device behavior/resource evidence.
- **G3.30** — at least 20 complete wake → command → response cycles.
- **G3.33** — 24-hour app stability smoke.

The same installed build should be used for all four unless a failure requires a code fix. If a fix is required, preserve the failed evidence and start a new identified session after the new APK is installed.

## Privacy boundary

Do not persist transcript text or the volatile `VoiceEventLedger` merely for test convenience. The collector stores device/resource aggregates and may pull the existing wake diagnostic metadata ledger. Diagnostic WAV retention remains governed by the existing consent/retention policy.

## Before the run

1. Verify `adb devices` shows exactly the target Fold4, or record the serial explicitly.
2. Install the debug APK built from the exact commit under test.
3. Record the APK workflow run ID and source commit.
4. Confirm the bridge is running and `127.0.0.1:8765` is reachable from the app.
5. Enroll the six local-wake templates if G2.8 is being measured.
6. Do not restart the local detector during the G2.8 latency session; a restart creates a new session ID.

## Start aggregate evidence collection

From the repository root, run for the intended observation interval. Ten minutes is the minimum useful sustained-idle sample; longer is preferred when practical.

```bash
python aihub/wakeword/fold4_evidence_session.py \
  --duration-seconds 600 \
  --interval-seconds 10 \
  --output-dir fold4_evidence
```

If multiple adb devices are attached, add `--serial <serial>`.

The collector writes:

- `session.json` — device fingerprint, model, Android/app identity and collection settings;
- `resource_samples.jsonl` — timestamped CPU/PSS/heap/battery/thermal metadata;
- `summary.json` — aggregate min/mean/max and observed process IDs/statuses;
- `wake_diagnostic_events.jsonl` — pulled only when available, using the existing app-owned diagnostic ledger.

## G2.8 + G3.30 active portion

Use one uninterrupted test block where practical.

For each of at least 20 intentional cycles:

1. Say the wake phrase naturally.
2. If wake is accepted, give a normal short command/question.
3. Wait for the response/TTS to finish and the app to return to wake-ready state.
4. Record the outcome in the table below. Do not silently retry or replace a failed cycle.

| # | Wake accepted | Command recognized | Response completed | Returned ready | Failure note |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |
| 7 | | | | | |
| 8 | | | | | |
| 9 | | | | | |
| 10 | | | | | |
| 11 | | | | | |
| 12 | | | | | |
| 13 | | | | | |
| 14 | | | | | |
| 15 | | | | | |
| 16 | | | | | |
| 17 | | | | | |
| 18 | | | | | |
| 19 | | | | | |
| 20 | | | | | |

After the active block, generate the strict G2.8 latency report:

```bash
python aihub/wakeword/v4_android_latency_report.py \
  --events fold4_evidence/wake_diagnostic_events.jsonl \
  --min-samples 20 \
  --require-complete \
  --output fold4_evidence/wake_latency_report.json
```

G2.8 remains open unless the strict report passes and identifies one Fold4/device/app/template/session with at least 20 accepted events.

G3.30 remains open unless at least 20 attempts are actually recorded and the resulting success/failure behavior is reviewed. A failure is evidence, not a reason to delete the attempt.

## G3.29 sustained idle

After the active cycle block, leave the app in its normal wake-ready state with the collector running. Preserve the complete resource samples rather than quoting a single `top` snapshot.

Review at least:

- sample duration and sample count;
- CPU mean/max;
- PSS mean/max;
- Java/native heap trend;
- battery level/temperature change;
- thermal status changes;
- process ID continuity/restart evidence;
- whether wake-ready behavior still works after idle.

Do not close G3.29 from a short process snapshot.

## G3.33 24-hour stability continuation

Keep the same build installed and leave the app in normal operating state toward 24 hours. Record any app/bridge restart, microphone loss, stuck listening/thinking state, failure to return to ready, or manual intervention.

At the 24-hour endpoint, perform at least one wake → command → response cycle again. G3.33 requires the app to remain usable, not merely for the Android process to exist.

## Evidence record

Record:

```text
source commit:
APK workflow run:
Fold4 model / fingerprint:
collection start/end:
collector command:
G2.8 accepted sample count:
G2.8 P50/P95:
G3.30 attempts / complete cycles / failures:
G3.29 idle duration and resource summary:
G3.33 24-hour endpoint result:
manual interventions/restarts:
artifact directory SHA-256/archive location:
```

Only after the applicable DoD is met should the master checklist checkbox be changed.
