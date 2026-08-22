# Okja physical-command classifier

This directory contains the offline training/evaluation tooling for the protected five-class command path:

```text
TV_ON
TV_OFF
AC_ON
AC_OFF
OTHER
```

The classifier is not generic ASR and does not produce text. Its output is consumed by `PhysicalCommandAuthorizer` and must pass explicit abstention/safety gates before it can authorize a device action.

## Runtime decision

Android inference uses LiteRT from Google Play services (`play-services-tflite-java:16.5.0`, system runtime only). Do **not** add `onnxruntime-android` to the Okja application while the sherpa-onnx AAR is present: sherpa-onnx v1.13.4 packages its own version-pinned `libonnxruntime.so`.

The candidate model contract is:

- 16 kHz mono PCM16 source;
- exactly 48,000 samples / 3.0 s for training;
- Android converts PCM16 to float32 `[-1, 1]`;
- TFLite input shape `[1, 48000]`;
- five output logits in the fixed class order above.

## 1. Collect real Fold4 audio

Use the Android launcher **Okja Command Dataset**.

Before recording, set an anonymous stable speaker ID and an acoustic condition such as `quiet`, `tv`, `kitchen`, `fan`, or `far-field`.

A new `session_id` is generated each time the activity is created. Deliberately collect multiple sessions: train/validation/test splitting is session-grouped to prevent near-duplicate leakage.

The app saves under its app-specific external-files directory:

```text
Android/data/com.soul.aihub/files/okja-physical-command-dataset/
  manifest.jsonl
  *.pcm16le
```

Each manifest row contains SHA-256, speaker/session/condition provenance, device/Android metadata, and PCM-continuity status. Capture now requires the first observed frame to be the start of a fresh `AudioEngine` epoch and writes exactly 48,000 samples.

## 2. Pull and validate the corpus

Example:

```bash
adb pull /sdcard/Android/data/com.soul.aihub/files/okja-physical-command-dataset ./okja-corpus
python aihub/command_classifier/validate_corpus.py ./okja-corpus --min-per-class 30
```

Validation fails on malformed provenance, wrong PCM format/length, SHA mismatch, duplicate bytes, unverified continuity, unsafe paths, or missing classes.

## 3. Train a candidate

```bash
python -m venv .venv-okja-command
source .venv-okja-command/bin/activate
pip install -r aihub/command_classifier/requirements.txt
python aihub/command_classifier/train_physical_classifier.py \
  ./okja-corpus \
  ./okja-command-output
```

The training script validates every row, splits by capture session, trains the small raw-waveform model, augments training data only, calibrates abstention thresholds on validation data, evaluates semantic safety on the separate test split, and exports TFLite.

The report also records speakers in each split and all speaker overlap. **Session-grouped is not the same as speaker-disjoint.** A model tested on overlapping speakers must not be described as validated for unseen-speaker generalization.

## Development gate encoded by the trainer

A `physical-command-qualified.tflite` file is emitted only when the held-out test set satisfies all of these:

- at least 3,000 physical-command examples;
- at least 1,000 `OTHER` examples;
- correct physical execution >= 98%;
- wrong device = 0;
- wrong ON/OFF action = 0;
- false physical execution from `OTHER` = 0.

This is only the development gate. Production qualification remains stricter, including the >=6,000 balanced physical-command inversion test and >=300 h representative household-negative protocol.

The script returns exit code `2` when the candidate is not deployment-qualified. A failed candidate remains useful for diagnostics but must not be copied into Android production assets.

## 4. Install only an explicit qualified artifact

```bash
python aihub/command_classifier/install_qualified_classifier.py \
  ./okja-command-output
```

The installer verifies the training report, development gate, exact class order, model SHA-256, and calibrated thresholds before creating the Android asset manifest. Android independently verifies that manifest/model again before constructing the LiteRT authorizer. Any failure leaves physical control reject-all.

## Data-quality rule

Synthetic TTS may later augment training or hard negatives, but it must not replace held-out real-speaker/Fold4 evidence. Production qualification metrics are calculated from real held-out audio.
