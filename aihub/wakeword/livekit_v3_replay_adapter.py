#!/usr/bin/env python3
"""Replay a PCM16 WAV through a LiveKit wakeword classifier.

The adapter mirrors LiveKit's microphone listener defaults: 16 kHz mono PCM,
80 ms frames, a 2 second sliding inference window, and a 2 second debounce.
Only threshold-crossing detections are written to stdout as JSONL so the output
can be consumed directly by ``v4_replay.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from array import array
from collections import deque
from importlib import metadata
from pathlib import Path
from typing import Callable, Mapping, Sequence

SAMPLE_RATE_HZ = 16000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
DEFAULT_FRAME_SAMPLES = 1280  # 80 ms at 16 kHz
DEFAULT_WINDOW_FRAMES = 25  # 2 seconds
DEFAULT_DEBOUNCE_MS = 2000

Predictor = Callable[[Sequence[int]], Mapping[str, float]]
PredictorFactory = Callable[[Path], Predictor]


def load_pcm16_wav(path: Path) -> array:
    """Load the exact WAV format accepted by the deterministic replay harness."""
    if not path.is_file():
        raise ValueError(f"audio file does not exist: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise ValueError("audio WAV must be uncompressed PCM")
            if wav.getframerate() != SAMPLE_RATE_HZ:
                raise ValueError(f"audio sample rate must be {SAMPLE_RATE_HZ} Hz")
            if wav.getnchannels() != CHANNELS:
                raise ValueError(f"audio must have {CHANNELS} channel")
            if wav.getsampwidth() != SAMPLE_WIDTH_BYTES:
                raise ValueError("audio must be PCM16")
            frames = wav.getnframes()
            if frames <= 0:
                raise ValueError("audio WAV must contain at least one frame")
            raw = wav.readframes(frames)
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"audio must be a readable WAV file: {path}") from exc

    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def installed_livekit_version() -> str:
    try:
        return metadata.version("livekit-wakeword")
    except metadata.PackageNotFoundError as exc:
        raise RuntimeError(
            "livekit-wakeword is not installed; install the pinned runtime before replay"
        ) from exc


def require_livekit_version(expected: str) -> str:
    actual = installed_livekit_version()
    if actual != expected:
        raise RuntimeError(
            f"livekit-wakeword version mismatch: expected {expected}, installed {actual}"
        )
    return actual


def create_livekit_predictor(model_path: Path) -> Predictor:
    try:
        import numpy as np
        from livekit.wakeword import WakeWordModel
    except ImportError as exc:
        raise RuntimeError(
            "LiveKit inference dependencies are unavailable; install livekit-wakeword"
        ) from exc

    model = WakeWordModel(models=[str(model_path)])

    def predict(samples: Sequence[int]) -> Mapping[str, float]:
        pcm = np.asarray(samples, dtype=np.int16)
        return model.predict(pcm)

    return predict


def replay_pcm(
    samples: Sequence[int],
    *,
    model_name: str,
    threshold: float,
    predictor: Predictor,
    frame_samples: int = DEFAULT_FRAME_SAMPLES,
    window_frames: int = DEFAULT_WINDOW_FRAMES,
    debounce_ms: int = DEFAULT_DEBOUNCE_MS,
) -> list[dict[str, float | str]]:
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be a finite number in [0, 1]")
    if frame_samples <= 0 or window_frames <= 0:
        raise ValueError("frame_samples and window_frames must be positive")
    if debounce_ms < 0:
        raise ValueError("debounce_ms must be non-negative")
    if not model_name.strip():
        raise ValueError("model_name is required")

    frame_buffer: deque[Sequence[int]] = deque(maxlen=window_frames)
    detections: list[dict[str, float | str]] = []
    last_detection_ms: float | None = None

    # Match the live listener: it only processes complete 80 ms frames.
    complete_samples = len(samples) - (len(samples) % frame_samples)
    for start in range(0, complete_samples, frame_samples):
        frame_buffer.append(samples[start : start + frame_samples])
        if len(frame_buffer) < window_frames:
            continue

        window = array("h")
        for frame in frame_buffer:
            window.extend(frame)
        scores = predictor(window)
        if model_name not in scores:
            available = ", ".join(sorted(scores)) or "none"
            raise RuntimeError(
                f"LiveKit score did not contain model {model_name!r}; available: {available}"
            )
        score = float(scores[model_name])
        if not math.isfinite(score):
            raise RuntimeError(f"LiveKit returned a non-finite score for {model_name!r}")

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
            # LiveKit's listener clears its two-second buffer after detection.
            frame_buffer.clear()

    return detections


def replay_wav(
    *,
    audio_path: Path,
    model_path: Path,
    model_name: str | None,
    threshold: float,
    frame_samples: int = DEFAULT_FRAME_SAMPLES,
    window_frames: int = DEFAULT_WINDOW_FRAMES,
    debounce_ms: int = DEFAULT_DEBOUNCE_MS,
    predictor_factory: PredictorFactory = create_livekit_predictor,
) -> list[dict[str, float | str]]:
    if not model_path.is_file():
        raise ValueError(f"model file does not exist: {model_path}")
    resolved_name = model_name or model_path.stem
    samples = load_pcm16_wav(audio_path)
    predictor = predictor_factory(model_path)
    return replay_pcm(
        samples,
        model_name=resolved_name,
        threshold=threshold,
        predictor=predictor,
        frame_samples=frame_samples,
        window_frames=window_frames,
        debounce_ms=debounce_ms,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LiveKit v3 offline replay adapter")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-name")
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--expected-engine-version", required=True)
    parser.add_argument("--frame-samples", type=int, default=DEFAULT_FRAME_SAMPLES)
    parser.add_argument("--window-frames", type=int, default=DEFAULT_WINDOW_FRAMES)
    parser.add_argument("--debounce-ms", type=int, default=DEFAULT_DEBOUNCE_MS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    require_livekit_version(args.expected_engine_version)
    rows = replay_wav(
        audio_path=args.audio,
        model_path=args.model,
        model_name=args.model_name,
        threshold=args.threshold,
        frame_samples=args.frame_samples,
        window_frames=args.window_frames,
        debounce_ms=args.debounce_ms,
    )
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
