#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import tensorflow as tf

from corpus import INPUT_SAMPLES, LABELS, SAMPLE_RATE_HZ, counts_by, load_corpus, split_by_session

SEED = 20260822
LABEL_TO_INDEX = {label: i for i, label in enumerate(LABELS)}


def load_arrays(rows):
    x = np.empty((len(rows), INPUT_SAMPLES), dtype=np.float32)
    y = np.empty((len(rows),), dtype=np.int32)
    for i, row in enumerate(rows):
        raw = np.fromfile(row.pcm_path, dtype="<i2")
        if raw.size != INPUT_SAMPLES:
            raise ValueError(f"{row.pcm_path.name}: expected {INPUT_SAMPLES} samples, got {raw.size}")
        x[i] = raw.astype(np.float32) / 32768.0
        y[i] = LABEL_TO_INDEX[row.label]
    return x, y


def shift_with_zeros(waveform: tf.Tensor, shift: tf.Tensor) -> tf.Tensor:
    def positive():
        keep = INPUT_SAMPLES - shift
        return tf.concat(
            [tf.zeros([shift], tf.float32), tf.slice(waveform, [0], [keep])], axis=0
        )

    def negative():
        amount = -shift
        keep = INPUT_SAMPLES - amount
        return tf.concat(
            [tf.slice(waveform, [amount], [keep]), tf.zeros([amount], tf.float32)], axis=0
        )

    result = tf.cond(shift > 0, positive, lambda: tf.cond(shift < 0, negative, lambda: waveform))
    result.set_shape([INPUT_SAMPLES])
    return result


def augment(waveform: tf.Tensor, label: tf.Tensor):
    gain = tf.random.uniform([], 0.70, 1.25)
    noise_std = tf.random.uniform([], 0.0, 0.012)
    shift = tf.random.uniform([], -2400, 2401, dtype=tf.int32)
    waveform = shift_with_zeros(waveform, shift)
    waveform = waveform * gain + tf.random.normal(tf.shape(waveform), stddev=noise_std)
    waveform = tf.clip_by_value(waveform, -1.0, 1.0)
    return waveform, label


def make_dataset(x, y, training: bool, batch_size: int):
    ds = tf.data.Dataset.from_tensor_slices((x, y))
    if training:
        ds = ds.shuffle(len(x), seed=SEED, reshuffle_each_iteration=True)
        ds = ds.map(augment, num_parallel_calls=tf.data.AUTOTUNE, deterministic=False)
    return ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def build_model() -> tf.keras.Model:
    inputs = tf.keras.Input(shape=(INPUT_SAMPLES,), dtype=tf.float32, name="pcm")
    x = tf.keras.layers.Reshape((INPUT_SAMPLES, 1))(inputs)
    x = tf.keras.layers.Conv1D(
        32, 129, strides=16, padding="same", use_bias=False, name="learned_frontend"
    )(x)
    x = tf.keras.layers.BatchNormalization()(x)
    x = tf.keras.layers.ReLU()(x)

    for i, (filters, stride) in enumerate(((48, 4), (64, 4), (96, 2)), start=1):
        x = tf.keras.layers.SeparableConv1D(
            filters,
            9,
            strides=stride,
            padding="same",
            use_bias=False,
            name=f"sepconv_{i}",
        )(x)
        x = tf.keras.layers.BatchNormalization()(x)
        x = tf.keras.layers.ReLU()(x)

    x = tf.keras.layers.GlobalAveragePooling1D()(x)
    x = tf.keras.layers.Dense(64, activation="relu")(x)
    x = tf.keras.layers.Dropout(0.20)(x)
    logits = tf.keras.layers.Dense(len(LABELS), name="logits")(x)
    return tf.keras.Model(inputs=inputs, outputs=logits, name="okja_physical_command_raw_pcm")


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp_values = np.exp(shifted)
    return exp_values / np.sum(exp_values, axis=1, keepdims=True)


def opposite_index(index: int) -> int:
    return {0: 1, 1: 0, 2: 3, 3: 2}[index]


def decide(prob: np.ndarray, thresholds: tuple[float, float, float]):
    min_conf, min_top2, min_opp = thresholds
    best = int(np.argmax(prob))
    if best == LABEL_TO_INDEX["OTHER"]:
        return None
    ordered = np.sort(prob)[::-1]
    top2_margin = float(ordered[0] - ordered[1])
    opp_margin = float(prob[best] - prob[opposite_index(best)])
    if float(prob[best]) < min_conf or top2_margin < min_top2 or opp_margin < min_opp:
        return None
    return best


def safety_metrics(y_true: np.ndarray, probabilities: np.ndarray, thresholds):
    metrics = {
        "physical_total": 0,
        "correct": 0,
        "physical_abstain": 0,
        "wrong_device": 0,
        "wrong_action": 0,
        "other_total": 0,
        "other_abstain": 0,
        "false_physical_execution": 0,
    }
    other = LABEL_TO_INDEX["OTHER"]
    for truth, prob in zip(y_true.tolist(), probabilities):
        prediction = decide(prob, thresholds)
        if truth == other:
            metrics["other_total"] += 1
            if prediction is None:
                metrics["other_abstain"] += 1
            else:
                metrics["false_physical_execution"] += 1
            continue

        metrics["physical_total"] += 1
        if prediction is None:
            metrics["physical_abstain"] += 1
        elif prediction == truth:
            metrics["correct"] += 1
        elif prediction // 2 != truth // 2:
            metrics["wrong_device"] += 1
        else:
            metrics["wrong_action"] += 1

    physical_total = max(1, metrics["physical_total"])
    other_total = max(1, metrics["other_total"])
    metrics["correct_execution_rate"] = metrics["correct"] / physical_total
    metrics["physical_abstention_rate"] = metrics["physical_abstain"] / physical_total
    metrics["false_physical_rate"] = metrics["false_physical_execution"] / other_total
    metrics["unsafe_count"] = (
        metrics["wrong_device"]
        + metrics["wrong_action"]
        + metrics["false_physical_execution"]
    )
    return metrics


def calibrate(y_true, probabilities, minimum_correct_rate: float):
    confidence_grid = np.round(np.arange(0.50, 1.00, 0.01), 2)
    top2_grid = np.array([0.00, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50])
    opposite_grid = np.array([0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80])

    candidates = []
    for confidence in confidence_grid:
        for top2 in top2_grid:
            for opposite in opposite_grid:
                thresholds = (float(confidence), float(top2), float(opposite))
                metrics = safety_metrics(y_true, probabilities, thresholds)
                if metrics["unsafe_count"] != 0:
                    continue
                if metrics["correct_execution_rate"] < minimum_correct_rate:
                    continue
                score = (
                    metrics["correct_execution_rate"],
                    opposite,
                    confidence,
                    top2,
                )
                candidates.append((score, thresholds, metrics))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, thresholds, metrics = candidates[0]
    return thresholds, metrics


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def speaker_split_metadata(split):
    speakers = {
        name: sorted({row.speaker_id for row in part})
        for name, part in split.items()
    }
    sets = {name: set(values) for name, values in speakers.items()}
    overlap = {
        "train_validation": sorted(sets["train"] & sets["validation"]),
        "train_test": sorted(sets["train"] & sets["test"]),
        "validation_test": sorted(sets["validation"] & sets["test"]),
    }
    return speakers, overlap


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train and safety-calibrate the Okja five-class raw-PCM command model"
    )
    parser.add_argument("corpus_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--min-per-class", type=int, default=30)
    parser.add_argument("--min-validation-correct-rate", type=float, default=0.98)
    parser.add_argument("--development-heldout-physical-min", type=int, default=3000)
    parser.add_argument("--development-heldout-other-min", type=int, default=1000)
    args = parser.parse_args()

    if args.epochs <= 0 or args.batch_size <= 0 or args.min_per_class <= 0:
        raise SystemExit("FAIL: epochs, batch-size, and min-per-class must be positive")
    if not 0.0 <= args.min_validation_correct_rate <= 1.0:
        raise SystemExit("FAIL: min-validation-correct-rate must be in [0, 1]")
    if args.development_heldout_physical_min <= 0 or args.development_heldout_other_min <= 0:
        raise SystemExit("FAIL: held-out development minimums must be positive")

    tf.keras.utils.set_random_seed(SEED)
    try:
        tf.config.experimental.enable_op_determinism()
    except Exception:
        pass

    rows = load_corpus(args.corpus_dir)
    counts = counts_by(rows, "label")
    for label in LABELS:
        if counts.get(label, 0) < args.min_per_class:
            raise SystemExit(
                f"FAIL: {label} has {counts.get(label, 0)} clips; "
                f"training minimum is {args.min_per_class}"
            )

    split = split_by_session(rows, seed=SEED)
    x_train, y_train = load_arrays(split["train"])
    x_val, y_val = load_arrays(split["validation"])
    x_test, y_test = load_arrays(split["test"])

    model = build_model()
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=["accuracy"],
    )

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=10, restore_best_weights=True
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=4, min_lr=1e-5
        ),
    ]

    history = model.fit(
        make_dataset(x_train, y_train, True, args.batch_size),
        validation_data=make_dataset(x_val, y_val, False, args.batch_size),
        epochs=args.epochs,
        callbacks=callbacks,
        verbose=2,
    )

    val_logits = model.predict(x_val, batch_size=args.batch_size, verbose=0)
    test_logits = model.predict(x_test, batch_size=args.batch_size, verbose=0)
    val_prob = softmax(val_logits)
    test_prob = softmax(test_logits)

    calibration = calibrate(
        y_val,
        val_prob,
        minimum_correct_rate=args.min_validation_correct_rate,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    keras_path = args.output_dir / "physical-command-candidate.keras"
    model.save(keras_path)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    tflite_bytes = converter.convert()
    candidate_path = args.output_dir / "physical-command-candidate.tflite"
    candidate_path.write_bytes(tflite_bytes)
    model_sha = sha256_bytes(tflite_bytes)

    split_speakers, speaker_overlap = speaker_split_metadata(split)
    report = {
        "schema": "okja.physical-command-training.v1",
        "seed": SEED,
        "tensorflow_version": tf.__version__,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "input_samples": INPUT_SAMPLES,
        "class_order": list(LABELS),
        "model_parameters": model.count_params(),
        "model_sha256": model_sha,
        "model_bytes": len(tflite_bytes),
        "corpus_counts": counts,
        "split_counts": {name: len(part) for name, part in split.items()},
        "split_sessions": {
            name: sorted({row.session_id for row in part}) for name, part in split.items()
        },
        "split_speakers": split_speakers,
        "speaker_overlap": speaker_overlap,
        "speaker_disjoint_split": all(not values for values in speaker_overlap.values()),
        "training_epochs_completed": len(history.history.get("loss", [])),
        "validation_calibration_found": calibration is not None,
        "deployment_allowed": False,
    }

    if calibration is not None:
        thresholds, val_metrics = calibration
        test_metrics = safety_metrics(y_test, test_prob, thresholds)
        threshold_record = {
            "schema": "okja.physical-command-thresholds.v1",
            "class_order": list(LABELS),
            "model_sha256": model_sha,
            "min_confidence": thresholds[0],
            "min_top_two_margin": thresholds[1],
            "min_opposite_action_margin": thresholds[2],
            "validation_metrics": val_metrics,
            "test_metrics": test_metrics,
        }
        candidate_thresholds = args.output_dir / "physical-command-candidate-thresholds.json"
        candidate_thresholds.write_text(
            json.dumps(threshold_record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report["thresholds"] = threshold_record

        development_gate = (
            test_metrics["physical_total"] >= args.development_heldout_physical_min
            and test_metrics["other_total"] >= args.development_heldout_other_min
            and test_metrics["correct_execution_rate"] >= 0.98
            and test_metrics["wrong_device"] == 0
            and test_metrics["wrong_action"] == 0
            and test_metrics["false_physical_execution"] == 0
        )
        report["development_gate"] = {
            "passed": development_gate,
            "required_heldout_physical": args.development_heldout_physical_min,
            "required_heldout_other": args.development_heldout_other_min,
            "required_correct_execution_rate": 0.98,
            "required_wrong_device": 0,
            "required_wrong_action": 0,
            "required_false_physical_execution": 0,
        }
        report["deployment_allowed"] = bool(development_gate)
        if development_gate:
            shutil.copy2(candidate_path, args.output_dir / "physical-command-qualified.tflite")
            shutil.copy2(
                candidate_thresholds,
                args.output_dir / "physical-command-qualified-thresholds.json",
            )
    else:
        report["development_gate"] = {
            "passed": False,
            "reason": "no validation threshold set achieved zero unsafe decisions and required correct rate",
        }

    report_path = args.output_dir / "training-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    # Candidate artifacts are diagnostic only. Only explicit qualified filenames can be installed.
    return 0 if report["deployment_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
