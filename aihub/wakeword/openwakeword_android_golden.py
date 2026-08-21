#!/usr/bin/env python3
"""Export deterministic openWakeWord golden vectors for Android parity testing.

This is not a production detector. It snapshots the pinned Python/openWakeWord 0.6.0
reference path so the future Android caller-owned-PCM implementation can verify its
melspectrogram/embedding/classifier wiring before any wake-quality decision.

The JSON intentionally contains one complete classifier input from a frame whose
history is composed only of real replay audio (no seeded initialization embeddings),
plus per-frame scores and provenance hashes. Android parity should compare floats
with a tolerance rather than requiring byte-identical tensors across runtimes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from importlib import metadata
from pathlib import Path
from typing import Any

from livekit_v3_replay_adapter import SAMPLE_RATE_HZ, load_pcm16_wav

FRAME_SAMPLES = 1280  # 80 ms at 16 kHz
SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_version(expected: str) -> str:
    try:
        actual = metadata.version("openwakeword")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError("openwakeword is not installed") from exc
    if actual != expected:
        raise RuntimeError(
            f"openwakeword version mismatch: expected {expected}, installed {actual}"
        )
    return actual


def _finite_float_list(values: Any) -> list[float]:
    flattened = values.reshape(-1).tolist()
    output = [float(value) for value in flattened]
    if not all(math.isfinite(value) for value in output):
        raise RuntimeError("reference feature tensor contains non-finite values")
    return output


def export_golden(
    *,
    audio_path: Path,
    classifier_path: Path,
    melspec_path: Path,
    embedding_path: Path,
    expected_engine_version: str,
    initialization_seed: int,
    output_path: Path,
) -> dict[str, Any]:
    for path in (audio_path, classifier_path, melspec_path, embedding_path):
        if not path.is_file():
            raise ValueError(f"required input does not exist: {path}")
    if not 0 <= initialization_seed <= 2**32 - 1:
        raise ValueError("initialization_seed must be in [0, 2**32 - 1]")

    engine_version = require_version(expected_engine_version)

    try:
        import numpy as np
        from openwakeword.model import Model
    except ImportError as exc:
        raise RuntimeError("openWakeWord inference dependencies are unavailable") from exc

    np.random.seed(initialization_seed)
    model = Model(
        wakeword_models=[str(classifier_path)],
        inference_framework="onnx",
        melspec_model_path=str(melspec_path),
        embedding_model_path=str(embedding_path),
    )

    model_name = classifier_path.stem
    if model_name not in model.model_inputs:
        available = ", ".join(sorted(model.model_inputs)) or "none"
        raise RuntimeError(
            f"classifier {model_name!r} was not loaded; available models: {available}"
        )

    input_frames = int(model.model_inputs[model_name])
    if input_frames <= 0:
        raise RuntimeError(f"invalid classifier input frame count: {input_frames}")

    samples = load_pcm16_wav(audio_path)
    complete_samples = len(samples) - (len(samples) % FRAME_SAMPLES)
    frame_count = complete_samples // FRAME_SAMPLES
    if frame_count < input_frames:
        raise RuntimeError(
            "audio is too short to produce a classifier window containing only real "
            f"audio embeddings: frames={frame_count}, required={input_frames}"
        )

    frame_scores: list[dict[str, float | int]] = []
    selected_features = None
    selected_shape: list[int] | None = None
    selected_score: float | None = None
    selected_frame_index: int | None = None

    for frame_index, start in enumerate(range(0, complete_samples, FRAME_SAMPLES)):
        pcm = np.asarray(samples[start : start + FRAME_SAMPLES], dtype=np.int16)
        scores = model.predict(pcm)
        if model_name not in scores:
            available = ", ".join(sorted(scores)) or "none"
            raise RuntimeError(
                f"score for {model_name!r} missing at frame {frame_index}; available: {available}"
            )
        score = float(scores[model_name])
        if not math.isfinite(score):
            raise RuntimeError(f"non-finite score at frame {frame_index}: {score}")

        timestamp_ms = (start + FRAME_SAMPLES) * 1000.0 / SAMPLE_RATE_HZ
        frame_scores.append(
            {
                "frame_index": frame_index,
                "timestamp_ms": timestamp_ms,
                "score": score,
            }
        )

        # Once at least input_frames real 80 ms windows have been supplied, the
        # latest classifier context no longer depends on openWakeWord's seeded
        # random feature-buffer priming. Keep the latest such frame as the Android
        # parity vector so production's fail-closed startup can be compared fairly.
        if frame_index + 1 >= input_frames:
            features = np.asarray(
                model.preprocessor.get_features(input_frames),
                dtype=np.float32,
            )
            if features.ndim < 2 or features.shape[-1] <= 0:
                raise RuntimeError(
                    f"unexpected classifier feature shape at frame {frame_index}: {features.shape}"
                )
            selected_features = _finite_float_list(features)
            selected_shape = [int(value) for value in features.shape]
            selected_score = score
            selected_frame_index = frame_index

    if selected_features is None or selected_shape is None or selected_score is None:
        raise RuntimeError("failed to capture a fully-real classifier feature window")

    embedding_dim = selected_shape[-1]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "android-openwakeword-feature-and-classifier-parity",
        "engine": {
            "name": "openwakeword",
            "version": engine_version,
            "framework": "onnx",
            "initialization_seed": initialization_seed,
        },
        "audio": {
            "sha256": sha256_file(audio_path),
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "frame_samples": FRAME_SAMPLES,
            "complete_frame_count": frame_count,
        },
        "models": {
            "classifier": {
                "name": model_name,
                "sha256": sha256_file(classifier_path),
                "input_frames": input_frames,
                "embedding_dim": embedding_dim,
            },
            "melspectrogram": {"sha256": sha256_file(melspec_path)},
            "embedding": {"sha256": sha256_file(embedding_path)},
        },
        "frame_scores": frame_scores,
        "selected_parity_frame": {
            "frame_index": selected_frame_index,
            "timestamp_ms": frame_scores[selected_frame_index]["timestamp_ms"],
            "score": selected_score,
            "classifier_input_shape": selected_shape,
            "classifier_input_float32": selected_features,
            "contains_only_real_audio_history": True,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export deterministic openWakeWord Android parity golden vectors"
    )
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--classifier", type=Path, required=True)
    parser.add_argument("--melspec-model", type=Path, required=True)
    parser.add_argument("--embedding-model", type=Path, required=True)
    parser.add_argument("--expected-engine-version", required=True)
    parser.add_argument("--initialization-seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    export_golden(
        audio_path=args.audio,
        classifier_path=args.classifier,
        melspec_path=args.melspec_model,
        embedding_path=args.embedding_model,
        expected_engine_version=args.expected_engine_version,
        initialization_seed=args.initialization_seed,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
