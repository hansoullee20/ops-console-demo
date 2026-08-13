#!/usr/bin/env python3
"""Deterministic offline replay harness for Okja wakeword engines.

The harness deliberately separates replay orchestration from a concrete model
runtime.  An adapter command receives pinned audio/model/threshold inputs and
prints detection JSONL to stdout.  The same adapter is executed repeatedly; any
change in normalized detections fails the replay instead of silently producing
non-reproducible benchmark evidence.

Adapter command tokens may contain these placeholders:
  {audio} {model} {threshold} {engine_id} {engine_version}

Each stdout JSON object must contain at least:
  timestamp_ms: number >= 0
  score: number

The emitted detections are directly consumable by v4_eval.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

REPLAY_SCHEMA_VERSION = 1
REQUIRED_SAMPLE_RATE_HZ = 16000
REQUIRED_CHANNELS = 1
REQUIRED_SAMPLE_WIDTH_BYTES = 2


@dataclass(frozen=True)
class AudioInfo:
    sha256: str
    sample_rate_hz: int
    channels: int
    sample_width_bytes: int
    frames: int
    duration_ms: int


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_wav(path: Path) -> AudioInfo:
    if not path.is_file():
        raise ValueError(f"audio file does not exist: {path}")
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            frames = wf.getnframes()
            compression = wf.getcomptype()
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"audio must be a readable WAV file: {path}") from exc

    if compression != "NONE":
        raise ValueError("audio WAV must be uncompressed PCM")
    if sample_rate != REQUIRED_SAMPLE_RATE_HZ:
        raise ValueError(f"audio sample rate must be {REQUIRED_SAMPLE_RATE_HZ} Hz")
    if channels != REQUIRED_CHANNELS:
        raise ValueError(f"audio must have {REQUIRED_CHANNELS} channel")
    if sample_width != REQUIRED_SAMPLE_WIDTH_BYTES:
        raise ValueError("audio must be PCM16")
    if frames <= 0:
        raise ValueError("audio WAV must contain at least one frame")

    return AudioInfo(
        sha256=sha256_file(path),
        sample_rate_hz=sample_rate,
        channels=channels,
        sample_width_bytes=sample_width,
        frames=frames,
        duration_ms=round(frames * 1000 / sample_rate),
    )


def _format_adapter_command(
    command: str | Sequence[str],
    *,
    audio: Path,
    model: Path,
    threshold: float,
    engine_id: str,
    engine_version: str,
) -> list[str]:
    tokens = shlex.split(command) if isinstance(command, str) else list(command)
    if not tokens:
        raise ValueError("adapter command must not be empty")
    values = {
        "audio": str(audio.resolve()),
        "model": str(model.resolve()),
        "threshold": format(threshold, ".12g"),
        "engine_id": engine_id,
        "engine_version": engine_version,
    }
    try:
        return [token.format(**values) for token in tokens]
    except KeyError as exc:
        raise ValueError(f"unknown adapter command placeholder: {exc.args[0]}") from exc


def _parse_adapter_stdout(stdout: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(stdout.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"adapter stdout line {line_no} is not JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"adapter stdout line {line_no} must be a JSON object")
        if not isinstance(row.get("timestamp_ms"), (int, float)) or row["timestamp_ms"] < 0:
            raise ValueError(f"adapter stdout line {line_no}: timestamp_ms must be >= 0")
        if not isinstance(row.get("score"), (int, float)):
            raise ValueError(f"adapter stdout line {line_no}: score must be numeric")
        rows.append(row)
    rows.sort(key=lambda row: (float(row["timestamp_ms"]), -float(row["score"])))
    return rows


def run_adapter(
    command: str | Sequence[str],
    *,
    audio: Path,
    model: Path,
    threshold: float,
    engine_id: str,
    engine_version: str,
    timeout_seconds: int = 300,
) -> list[dict[str, Any]]:
    argv = _format_adapter_command(
        command,
        audio=audio,
        model=model,
        threshold=threshold,
        engine_id=engine_id,
        engine_version=engine_version,
    )
    proc = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(
            f"adapter failed with exit code {proc.returncode}"
            + (f": {stderr}" if stderr else "")
        )
    return _parse_adapter_stdout(proc.stdout)


def _normalize_detections(
    rows: Iterable[dict[str, Any]],
    *,
    engine_id: str,
    engine_version: str,
    model_sha256: str,
    audio_sha256: str,
    threshold: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        normalized = dict(row)
        normalized.update(
            {
                "timestamp_ms": float(row["timestamp_ms"]),
                "score": float(row["score"]),
                "engine": engine_id,
                "version": engine_version,
                "model": model_sha256,
                "threshold": float(threshold),
                "audio_sha256": audio_sha256,
            }
        )
        out.append(normalized)
    return out


def _canonical(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def replay(
    *,
    audio: Path,
    model: Path,
    engine_id: str,
    engine_version: str,
    threshold: float,
    adapter_command: str | Sequence[str],
    repeats: int = 2,
    timeout_seconds: int = 300,
    audio_source: str | None = None,
    model_source: str | None = None,
    adapter_source: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if repeats < 2:
        raise ValueError("repeats must be at least 2 to verify deterministic replay")
    if not engine_id.strip() or not engine_version.strip():
        raise ValueError("engine_id and engine_version are required")
    if not isinstance(threshold, (int, float)):
        raise ValueError("threshold must be numeric")
    if not model.is_file():
        raise ValueError(f"model file does not exist: {model}")

    audio_info = inspect_wav(audio)
    model_sha = sha256_file(model)
    baseline: list[dict[str, Any]] | None = None
    baseline_canonical: str | None = None

    for attempt in range(repeats):
        raw = run_adapter(
            adapter_command,
            audio=audio,
            model=model,
            threshold=float(threshold),
            engine_id=engine_id,
            engine_version=engine_version,
            timeout_seconds=timeout_seconds,
        )
        normalized = _normalize_detections(
            raw,
            engine_id=engine_id,
            engine_version=engine_version,
            model_sha256=model_sha,
            audio_sha256=audio_info.sha256,
            threshold=float(threshold),
        )
        canonical = _canonical(normalized)
        if baseline is None:
            baseline = normalized
            baseline_canonical = canonical
        elif canonical != baseline_canonical:
            raise RuntimeError(
                f"non-deterministic replay: attempt {attempt + 1} differs from attempt 1"
            )

    assert baseline is not None
    manifest = {
        "replay_schema_version": REPLAY_SCHEMA_VERSION,
        "deterministic": True,
        "repeat_count": repeats,
        "audio_filename": audio.name,
        "audio_sha256": audio_info.sha256,
        "sample_rate_hz": audio_info.sample_rate_hz,
        "channels": audio_info.channels,
        "duration_ms": audio_info.duration_ms,
        "model_filename": model.name,
        "model_sha256": model_sha,
        "engine": engine_id,
        "engine_version": engine_version,
        "threshold": float(threshold),
        "adapter_command": list(adapter_command) if not isinstance(adapter_command, str) else adapter_command,
        "detection_count": len(baseline),
    }
    if audio_source:
        manifest["audio_source"] = audio_source
    if model_source:
        manifest["model_source"] = model_source
    if adapter_source:
        manifest["adapter_source"] = adapter_source
    return baseline, manifest


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deterministic offline wakeword replay")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--engine-id", required=True)
    parser.add_argument("--engine-version", required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--adapter-command", required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--audio-source")
    parser.add_argument("--model-source")
    parser.add_argument("--adapter-source")
    parser.add_argument("--detections-out", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    rows, manifest = replay(
        audio=args.audio,
        model=args.model,
        engine_id=args.engine_id,
        engine_version=args.engine_version,
        threshold=args.threshold,
        adapter_command=args.adapter_command,
        repeats=args.repeats,
        timeout_seconds=args.timeout_seconds,
        audio_source=args.audio_source,
        model_source=args.model_source,
        adapter_source=args.adapter_source,
    )
    write_jsonl(args.detections_out, rows)
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
