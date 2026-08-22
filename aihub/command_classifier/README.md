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

Before recording, set:

- `speaker id`: anonymous stable speaker identifier such as `speaker-01`;
- `condition`: e.g. `quiet`, `tv`, `kitchen`, `fan`, `far-field`.

A new `session_id` is generated each time the activity is created. Do not force all recordings into one session: train/validation/test splitting is session-grouped to prevent near-duplicate leakage.

The app saves data under its app-specific external-files directory:

```text
Android/data/com.soul.aihub/files/okja-physical-command-dataset/
  manifest.jsonl
  *.pcm16le
```

Each manifest row contains SHA-256, speaker/session/condition provenance, device/Android metadata, and a flag confirming PCM continuity from `AudioEngine`.

## 2. Pull and validate the corpus

Example with adb:

```bash
adb pull /sdcard/Android/data/com.soul.aihub/files/okja-physical-command-dataset ./okja-corpus
python aihub/command_classifier/validate_corpus.py ./okja-corpus --min-per-class 30
```

Validation fails on:

- missing or malformed provenance;
- non-16-kHz/non-mono/non-PCM16 records;
- PCM size mismatch;
- SHA-256 mismatch;
- duplicate audio bytes;
- unverified PCM continuity;
- missing classes.

## 3. Train a candidate

Create a dedicated environment and install the pinned training dependency:

```bash
python -m venv .venv-okja-command
source .venv-okja-command/bin/activate
pip install -r aihub/command_classifier/requirements.txt
python aihub/command_classifier/train_physical_classifier.py \
  ./okja-corpus \
  ./okja-command-output
```

The training script:

1. validates every corpus row;
2. splits by whole capture session, never individual clip;
3. trains a small raw-waveform 1-D depthwise/separable CNN;
4. performs gain/noise/time-shift augmentation on training data only;
5. calibrates confidence, top-two margin, and explicit opposite-action margin on validation data;
6. evaluates semantic physical-command safety on a separate test split;
7. exports a float-input TFLite candidate and a threshold JSON record.

The script returns exit code `2` unless the development gate is met. A non-qualified candidate remains useful for diagnostics but must not be copied into the production asset path.

## Development gate encoded by the trainer

A `physical-command-qualified.tflite` file is emitted only when the held-out test set satisfies all of these:

- at least 3,000 physical-command examples;
- correct physical execution >= 98%;
- wrong device = 0;
- wrong ON/OFF action = 0;
- false physical execution rate on `OTHER` < 0.1%.

This is only the development gate. Production qualification still requires the larger Okja release protocol, including long household-negative testing and the final 6,000-trial opposite-action gate.

## Data-quality rule

Synthetic TTS may be added later for augmentation/hard-negative generation, but it must not substitute for held-out real-speaker/Fold4 evidence. Production qualification metrics are calculated from real held-out audio.
