#!/usr/bin/env python3
"""Replay a PCM16 WAV through the openWakeWord streaming runtime.

The adapter feeds exact 80 ms frames to openWakeWord and preserves its native
feature/prediction state, including the runtime's initial warm-up behavior. It
prints only threshold-crossing detections as JSONL for ``v4_replay.py``.
"""

from __future__ import annotations

import argparse
import json
import math
from importlib import metadata
from pathlib import Path
from typing import Callable, Mapping, Sequence

from livekit_v3_replay_adapter import SAMPLE_RATE_HZ, load_pcm16_wav

DEFAULT_FRAME_SAMPLES = 1280  # 80 ms at 16 kHz
DEFAULT_DEBOUNCE_MS = 2000

FramePredictor = Callable[[Sequence[int]], Mapping[str, float]]
PredictorFactory = Callable[[Path], FramePredictor]


def installed_openwakeword_version() -> str:
    try:
        return metadata.version("openwakeword")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "openwakeword is not installed; install the pinned runtime before replay"
        ) from exc


def require_openwakeword_version(expected: str) -> str:
    actual = installed_openwakeword_version()
    if actual != expected:
        raise RuntimeError(
            f"openwakeword version mismatch: expected {expected}, installed {actual}"
        )
    return actual


def create_openwakeword_predictor(model_path: Path) -> FramePredictor:
    try:
        import numpy as np
        from openwakeword.model import Model
    except ImportError as exc:
        raise RuntimeError(
            "openWakeWord inference dependencies are unavailable; install openwakeword"
        ) from exc

    model = Model(
        wakeword_models=[str(model_path)],
        inference_framework="onnx",
    )

    def predict(frame: Sequence[int]) -> Mapping[str, float]:
        pcm = np.asarray(frame, dtype=np.int16)
        return model.predict(pcm)

    return predict


def replay_stream(
    samples: Sequence[int],
    *,
    model_name: str,
    threshold: float,
    predictor: FramePredictor,
    frame_samples: int = DEFAULT_FRAME_SAMPLES,
    debounce_ms: int = DEFAULT_DEBOUNCE_MS,
) -> list[dict[str, float | str]]:
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be a finite number in [0, 1]")
    if frame_samples <= 0:
        raise ValueError("frame_samples must be positive")
    if debounce_ms < 0:
        raise ValueError("debounce_ms must be non-negative")
    if not model_name.strip():
        raise ValueError("model_name is required")

    detections: list[dict[str, float | str]] = []
    last_detection_ms: float | None = None
    complete_samples = len(samples) - (len(samples) % frame_samples)

    for start in range(0, complete_samples, frame_samples):
        scores = predictor(samples[start : start + frame_samples])
        if model_name not in scores:
            available = ", ".join(sorted(scores)) or "none"
            raise RuntimeError(
                f"openWakeWord score did not contain model {model_name!r}; "
                f"available: {available}"
            )
        score = float(scores[model_name])
        if not math.isfinite(score):
            raise RuntimeError(
                f"openWakeWord returned a non-finite score for {model_name!r}"
            )

        timestamp_ms = (start + frame_samples) * 1000 / SAMPLE_RATE_HZ
        outside_debounce = (
            last_detection_ms is None
            or timestamp_ms - last_detection_ms >= debounce_ms
        )
        if score >= threshold and outside_debounce:
            detections.append(
                {
                    "timestamp_ms": timestamp_ms,
                    "score": score,
                    "model_name": model_name,
                }
            )
            last_detection_ms = timestamp_ms

    return detections


def replay_wav(
    *,
    audio_path: Path,
    model_path: Path,
    model_name: str | None,
    threshold: float,
    frame_samples: int = DEFAULT_FRAME_SAMPLES,
    debounce_ms: int = DEFAULT_DEBOUNCE_MS,
    predictor_factory: PredictorFactory = create_openwakeword_predictor,
) -> list[dict[str, float | str]]:
    if not model_path.is_file():
        raise ValueError(f"model file does not exist: {model_path}")
    resolved_name = model_name or model_path.stem
    samples = load_pcm16_wav(audio_path)
    predictor = predictor_factory(model_path)
    return replay_stream(
        samples,
        model_name=resolved_name,
        threshold=threshold,
        predictor=predictor,
        frame_samples=frame_samples,
        debounce_ms=debounce_ms,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="openWakeWord offline replay adapter")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-name")
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--expected-engine-version", required=True)
    parser.add_argument("--frame-samples", type=int, default=DEFAULT_FRAME_SAMPLES)
    parser.add_argument("--debounce-ms", type=int, default=DEFAULT_DEBOUNCE_MS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    require_openwakeword_version(args.expected_engine_version)
    rows = replay_wav(
        audio_path=args.audio,
        model_path=args.model,
        model_name=args.model_name,
        threshold=args.threshold,
        frame_samples=args.frame_samples,
        debounce_ms=args.debounce_ms,
    )
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
