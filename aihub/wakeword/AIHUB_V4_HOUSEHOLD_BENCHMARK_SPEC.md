# Okja v4 Household Benchmark Specification

Status: active implementation contract for TEST C / TEST D capture and offline wakeword comparison.

## Scope

This benchmark is the fixed real-world reference for comparing v3, v4, and alternative local/open wakeword engines. Synthetic validation must not replace it.

`TEST_D` is immutable evaluation data. It is never training data, never threshold-selection data, and never augmentation source material.

## Files per recording

For each recording session keep these logical records:

- one WAV recording;
- one session metadata JSON object / JSONL row;
- zero or more intentional-wake ground-truth JSONL rows;
- one detection JSONL per model/version/threshold sweep or replay output.

Machine-readable field definitions live in `v4_benchmark_schema.json`. Runtime validation and marker CLI live in `v4_benchmark_contract.py`.

## WAV naming

Use a basename only, with no directory separators:

`YYYYMMDDTHHMMSSZ__<device_id>__<room_id>__<recording_id>.wav`

Example:

`20260813T080000Z__fold4-01__livingroom__livingroom-20260813-001.wav`

The validator requires the filename to end in `.wav` and include the exact `device_id`, `room_id`, and `recording_id`. The session row stores the WAV SHA-256 so renamed or modified audio cannot silently pass as the same benchmark item.

## Session metadata

Required provenance includes:

- schema version;
- benchmark ID and recording ID;
- TEST A/B/C/D assignment;
- device ID and room ID;
- wall-clock start timestamp and duration;
- WAV filename, sample rate, channel count, and audio SHA-256;
- firmware/app version;
- firmware Git SHA and active benchmark-model SHA;
- consent recorded flag;
- retention class;
- training eligibility.

For `TEST_D` the validator additionally requires:

- `training_eligible=false`;
- `immutable=true`;
- `retention_class=benchmark_fixed`.

## Intentional wake markers

Intentional invocations are appended as ground-truth JSONL. Each event records:

- event ID and recording ID;
- offset in milliseconds from the recording start;
- exact phrase and language;
- speaker ID;
- room, condition, background;
- optional distance, direction, and voice level;
- `mention_context` distinction.

Example marker command:

```bash
python v4_benchmark_contract.py mark-wake \
  --output truth.jsonl \
  --recording-id livingroom-20260813-001 \
  --timestamp-ms 185420 \
  --phrase '옥자야' \
  --speaker-id grandmother \
  --room-id livingroom \
  --background tv \
  --distance-m 2.5 \
  --direction front \
  --voice-level normal
```

The emitted row is immediately validated before it is appended.

## Detection JSONL

Each model detection records:

- detection ID and recording ID;
- offset milliseconds;
- model name, model version, exact model SHA;
- threshold and score;
- device ID;
- optional room, accepted/rejected flag, latency, and metadata.

One physical trigger may produce multiple raw model candidates. During scoring `v4_eval.py` performs one-to-one matching: the first matched detection can satisfy an intentional event, while unmatched or duplicate detections remain false positives.

## Negative exposure

FPPH denominator is negative listening exposure only. Exclude intentional-invocation windows from the negative exposure calculation rather than pretending a 24-hour file contributes a full 24 negative hours when intentional wakes were inserted.

Report both FPPH and false alarms/day. Zero observed false alarms must still carry a confidence upper bound.

## Threshold policy

Thresholds may be swept on development/validation data. Do not select or retune a threshold from the frozen TEST D result. TEST D is for final comparison of already selected candidate settings.

## Validation

Examples:

```bash
python v4_benchmark_contract.py validate session session.jsonl
python v4_benchmark_contract.py validate truth truth.jsonl
python v4_benchmark_contract.py validate detection detections.jsonl
```

CI runs both evaluator and benchmark-contract unit tests through `Okja v4 Evaluator Tests`.

## Next implementation step

The remaining G2 capture-side work is the on-device ring-buffer candidate logger and manual missed-wake capture. This specification deliberately does not claim those are complete.
