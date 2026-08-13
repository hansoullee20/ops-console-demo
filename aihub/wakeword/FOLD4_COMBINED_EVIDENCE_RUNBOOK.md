# Okja Fold4 combined evidence runbook

This runbook combines the currently blocked target-device work without changing privacy policy or pretending software tests are physical evidence.

## Gates covered

- **G2.8** — target Android P50/P95 wake latency, minimum 20 accepted wake attempts.
- **G3.29** — sustained-idle target-device behavior/resource evidence.
- **G3.30** — at least 20 complete wake → command → response cycles.
- **G3.33** — 24-hour app stability smoke.

The same installed build should be used for all four unless a failure requires a code fix. If a fix is required, preserve the failed evidence and start a new identified session after the new APK is installed.

## Privacy boundary

Do not persist transcript text or the volatile `VoiceEventLedger` merely for test convenience. Diagnostic WAV retention remains governed by the existing consent/retention policy.

## Collector status

`fold4_evidence_session.py` is **provisional tooling, not gate evidence yet**. Its metadata/PSS/battery collection path is useful, but its Android `top` CPU parser has not yet been verified against the target Fold4's exact Toybox output. Some Android builds place `%CPU` only in the header while row values omit the percent sign. Until that parser is verified/fixed and the collector itself is checked on the Fold4, do not use its CPU field as the sole basis for G3.29 closure.

The strict G2.8 latency path in `v4_android_latency_report.py` is separate and remains the authoritative latency report.

## Before the run

1. Verify `adb devices` shows exactly the target Fold4, or record the serial explicitly.
2. Install the debug APK built from the exact commit under test.
3. Record the APK workflow run ID and source commit.
4. Confirm the bridge is running and `127.0.0.1:8765` is reachable from the app.
5. Enroll the six local-wake templates if G2.8 is being measured.
6. Do not restart the local detector during the G2.8 latency session; a restart creates a new session ID.

## Provisional aggregate evidence collection

After the collector parser is verified on the Fold4, the intended command is:

```bash
python aihub/wakeword/fold4_evidence_session.py \
  --duration-seconds 600 \
  --interval-seconds 10 \
  --output-dir fold4_evidence
```

If multiple adb devices are attached, add `--serial <serial>`.

The collector writes device/resource aggregates and may pull the existing wake diagnostic metadata ledger. It does not intentionally persist transcript text or raw microphone audio.

## G2.8 + G3.30 active portion

Use one uninterrupted test block where practical.

For each of at least 20 intentional cycles:

1. Say the wake phrase naturally.
2. If wake is accepted, give a normal short command/question.
3. Wait for the response/TTS to finish and the app to return to wake-ready state.
4. Record the outcome. Do not silently retry or replace a failed cycle.

Use `FOLD4_FULL_CYCLE_RECORD.csv` for the durable attempt record.

After the active block, pull the existing wake diagnostic ledger and generate the strict G2.8 latency report:

```bash
adb exec-out run-as com.soul.aihub \
  cat files/wake_diagnostics/wake_diagnostic_events.jsonl \
  > wake_diagnostic_events.jsonl

python aihub/wakeword/v4_android_latency_report.py \
  --events wake_diagnostic_events.jsonl \
  --min-samples 20 \
  --require-complete \
  --output wake_latency_report.json
```

G2.8 remains open unless the strict report passes and identifies one Fold4/device/app/template/session with at least 20 accepted events.

G3.30 remains open unless at least 20 attempts are actually recorded and the resulting success/failure behavior is reviewed. A failure is evidence, not a reason to delete the attempt.

## G3.29 sustained idle

After the active cycle block, leave the app in its normal wake-ready state. Preserve a sustained sequence of resource measurements rather than quoting one `top` snapshot.

Review at least:

- sample duration and sample count;
- CPU mean/max from a verified sampling method;
- PSS mean/max;
- Java/native heap trend;
- battery level/temperature change;
- thermal status changes;
- process ID continuity/restart evidence;
- whether wake-ready behavior still works after idle.

Do not close G3.29 from a short process snapshot or from the provisional collector's CPU field until its parser is verified on the target Fold4.

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
resource-sampling method:
G2.8 accepted sample count:
G2.8 P50/P95:
G3.30 attempts / complete cycles / failures:
G3.29 idle duration and resource summary:
G3.33 24-hour endpoint result:
manual interventions/restarts:
artifact directory SHA-256/archive location:
```

Only after the applicable DoD is met should the master checklist checkbox be changed.
