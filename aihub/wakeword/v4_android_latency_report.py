#!/usr/bin/env python3
"""Summarize target-Android wake latency diagnostics as P50/P95 evidence.

The Android detector records monotonic VAD-onset, segment-end and decision
timestamps in its privacy-scoped candidate JSONL. This tool reads only the
event metadata; it does not need or retain the captured WAV files.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LATENCY_DEFINITION = "vad_onset_to_decision_monotonic"
MEASUREMENT_CLOCK = "android.os.SystemClock.elapsedRealtime"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class LatencySample:
    event_id: str
    session_id: str
    latency_ms: float
    post_segment_processing_ms: float
    device_manufacturer: str
    device_model: str
    device_sdk_int: int
    device_fingerprint: str
    app_version: str
    model_name: str
    model_version: str
    model_sha: str


def _required_text(metadata: dict[str, Any], key: str, source: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: metadata.{key} must be non-empty text")
    return value.strip()


def _required_number(metadata: dict[str, Any], key: str, source: str) -> float:
    value = metadata.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{source}: metadata.{key} must be a finite number")
    return float(value)


def _parse_instrumented_sample(row: dict[str, Any], source: str) -> LatencySample | None:
    if row.get("kind") != "candidate" or row.get("accepted") is not True:
        return None
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None
    if "latency_schema_version" not in metadata:
        return None
    if metadata.get("latency_schema_version") != 1:
        raise ValueError(f"{source}: unsupported latency_schema_version")
    if metadata.get("latency_definition") != LATENCY_DEFINITION:
        raise ValueError(f"{source}: unexpected latency_definition")
    if metadata.get("measurement_clock") != MEASUREMENT_CLOCK:
        raise ValueError(f"{source}: unexpected measurement_clock")

    onset = _required_number(metadata, "vad_onset_monotonic_ms", source)
    segment_end = _required_number(metadata, "segment_end_monotonic_ms", source)
    decision = _required_number(metadata, "decision_monotonic_ms", source)
    latency = _required_number(metadata, "wake_latency_ms", source)
    processing = _required_number(metadata, "post_segment_processing_ms", source)
    segment_duration = _required_number(metadata, "segment_duration_ms", source)
    if onset < 0 or not onset <= segment_end <= decision:
        raise ValueError(f"{source}: monotonic timestamps are out of order")
    if min(latency, processing, segment_duration) < 0:
        raise ValueError(f"{source}: latency durations must be non-negative")
    if abs(latency - (decision - onset)) > 0.001:
        raise ValueError(f"{source}: wake_latency_ms disagrees with timestamps")
    if abs(processing - (decision - segment_end)) > 0.001:
        raise ValueError(f"{source}: post_segment_processing_ms disagrees with timestamps")
    if abs(segment_duration - (segment_end - onset)) > 0.001:
        raise ValueError(f"{source}: segment_duration_ms disagrees with timestamps")

    event_id = row.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError(f"{source}: event_id must be non-empty text")
    model_sha = _required_text(metadata, "model_sha", source).lower()
    if not SHA256_RE.fullmatch(model_sha):
        raise ValueError(f"{source}: metadata.model_sha must be a lowercase SHA-256")
    sdk = metadata.get("device_sdk_int")
    if not isinstance(sdk, int) or isinstance(sdk, bool) or sdk <= 0:
        raise ValueError(f"{source}: metadata.device_sdk_int must be a positive integer")

    return LatencySample(
        event_id=event_id,
        session_id=_required_text(metadata, "session_id", source),
        latency_ms=latency,
        post_segment_processing_ms=processing,
        device_manufacturer=_required_text(metadata, "device_manufacturer", source),
        device_model=_required_text(metadata, "device_model", source),
        device_sdk_int=sdk,
        device_fingerprint=_required_text(metadata, "device_fingerprint", source),
        app_version=_required_text(metadata, "app_version", source),
        model_name=_required_text(metadata, "model_name", source),
        model_version=_required_text(metadata, "model_version", source),
        model_sha=model_sha,
    )


def load_samples(path: Path) -> tuple[list[LatencySample], int]:
    samples: list[LatencySample] = []
    ignored_uninstrumented = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            source = f"{path}:{line_number}"
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source}: invalid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{source}: row must be an object")
            sample = _parse_instrumented_sample(row, source)
            if sample is not None:
                samples.append(sample)
            elif row.get("kind") == "candidate" and row.get("accepted") is True:
                ignored_uninstrumented += 1
    return samples, ignored_uninstrumented


def percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile without samples")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * probability
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def _one_value(samples: list[LatencySample], attribute: str, label: str) -> Any:
    values = {getattr(sample, attribute) for sample in samples}
    if len(values) != 1:
        raise ValueError(f"selected session mixes {label}: {sorted(values)!r}")
    return next(iter(values))


def summarize(
    samples: list[LatencySample],
    ignored_uninstrumented: int = 0,
    session_id: str | None = None,
    min_samples: int = 20,
) -> dict[str, Any]:
    if min_samples <= 0:
        raise ValueError("min_samples must be positive")
    if not samples:
        raise ValueError("no instrumented accepted wake events found")
    available_sessions = list(dict.fromkeys(sample.session_id for sample in samples))
    selected_session = session_id or samples[-1].session_id
    selected = [sample for sample in samples if sample.session_id == selected_session]
    if not selected:
        raise ValueError(f"session_id not found: {selected_session}")

    latencies = [sample.latency_ms for sample in selected]
    processing = [sample.post_segment_processing_ms for sample in selected]
    report = {
        "schema_version": 1,
        "latency_definition": LATENCY_DEFINITION,
        "measurement_clock": MEASUREMENT_CLOCK,
        "selected_session_id": selected_session,
        "available_session_ids": available_sessions,
        "sample_count": len(selected),
        "required_sample_count": min_samples,
        "measurement_complete": len(selected) >= min_samples,
        "ignored_uninstrumented_accepted_events": ignored_uninstrumented,
        "target_device": {
            "manufacturer": _one_value(selected, "device_manufacturer", "manufacturers"),
            "model": _one_value(selected, "device_model", "device models"),
            "sdk_int": _one_value(selected, "device_sdk_int", "Android SDK versions"),
            "fingerprint": _one_value(selected, "device_fingerprint", "device fingerprints"),
        },
        "app_version": _one_value(selected, "app_version", "app versions"),
        "model": {
            "name": _one_value(selected, "model_name", "model names"),
            "version": _one_value(selected, "model_version", "model versions"),
            "sha256": _one_value(selected, "model_sha", "model SHAs"),
        },
        "wake_latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "mean": statistics.fmean(latencies),
            "min": min(latencies),
            "max": max(latencies),
        },
        "post_segment_processing_ms": {
            "p50": percentile(processing, 0.50),
            "p95": percentile(processing, 0.95),
            "mean": statistics.fmean(processing),
        },
        "event_ids": [sample.event_id for sample in selected],
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    try:
        samples, ignored = load_samples(args.events)
        report = summarize(samples, ignored, args.session_id, args.min_samples)
    except ValueError as exc:
        parser.error(str(exc))

    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.require_complete and not report["measurement_complete"]:
        print(
            f"need {report['required_sample_count']} accepted events; "
            f"found {report['sample_count']}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
