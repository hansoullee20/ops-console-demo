#!/usr/bin/env python3
"""Okja v4 wakeword benchmark evaluator.

Consumes ground-truth JSONL and candidate-detection JSONL, performs one-to-one
matching, reports recall/miss/FPPH/false-alarms-per-day/latency, group
breakdowns, statistical confidence, and deterministic threshold sweeps.

TEST D policy: this evaluator reads benchmark annotations/detections only; it
does not mutate or create training manifests.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

DEFAULT_PRE_TOLERANCE_MS = 500
DEFAULT_POST_TOLERANCE_MS = 1500


@dataclass(frozen=True)
class Truth:
    event_id: str
    timestamp_ms: float
    phrase: str = ""
    speaker: str = ""
    condition: str = ""
    room: str = ""
    background: str = ""
    distance_m: float | None = None
    direction: str = ""
    voice_level: str = ""
    self_tts: bool | None = None
    time_bucket: str = ""


@dataclass(frozen=True)
class Detection:
    timestamp_ms: float
    score: float
    model: str = ""
    version: str = ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    return rows


def load_truth(path: Path) -> list[Truth]:
    out: list[Truth] = []
    for i, row in enumerate(_read_jsonl(path), 1):
        if row.get("intentional_invocation", True) is False:
            continue
        ts = row.get("timestamp_ms", row.get("offset_ms"))
        if ts is None:
            raise ValueError(f"{path}: truth row {i} missing timestamp_ms/offset_ms")
        out.append(
            Truth(
                event_id=str(row.get("event_id", f"truth-{i}")),
                timestamp_ms=float(ts),
                phrase=str(row.get("phrase", "")),
                speaker=str(row.get("speaker", row.get("speaker_id", ""))),
                condition=str(row.get("condition", "")),
                room=str(row.get("room", row.get("room_id", ""))),
                background=str(row.get("background", "")),
                distance_m=(float(row["distance_m"]) if row.get("distance_m") is not None else None),
                direction=str(row.get("direction", "")),
                voice_level=str(row.get("voice_level", "")),
                self_tts=(row.get("self_tts") if isinstance(row.get("self_tts"), bool) else None),
                time_bucket=str(row.get("time_bucket", "")),
            )
        )
    return sorted(out, key=lambda x: x.timestamp_ms)


def load_detections(path: Path) -> list[Detection]:
    out: list[Detection] = []
    for i, row in enumerate(_read_jsonl(path), 1):
        ts = row.get("timestamp_ms", row.get("offset_ms"))
        if ts is None:
            raise ValueError(f"{path}: detection row {i} missing timestamp_ms/offset_ms")
        if "score" not in row:
            raise ValueError(f"{path}: detection row {i} missing score")
        out.append(
            Detection(
                timestamp_ms=float(ts),
                score=float(row["score"]),
                model=str(row.get("model", "")),
                version=str(row.get("version", "")),
            )
        )
    return sorted(out, key=lambda x: x.timestamp_ms)


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 1.0)
    p = successes / total
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2 * total)) / denom
    half = z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def poisson_rate_ci_95(count: int, exposure_hours: float) -> dict[str, float | None]:
    if exposure_hours <= 0:
        return {"lower_per_hour": None, "upper_per_hour": None}
    if count == 0:
        upper = -math.log(0.05) / exposure_hours
        return {"lower_per_hour": 0.0, "upper_per_hour": upper}
    rate = count / exposure_hours
    se = math.sqrt(count) / exposure_hours
    return {
        "lower_per_hour": max(0.0, rate - 1.96 * se),
        "upper_per_hour": rate + 1.96 * se,
    }


def match_events(
    truth: list[Truth],
    detections: list[Detection],
    threshold: float,
    pre_tolerance_ms: float = DEFAULT_PRE_TOLERANCE_MS,
    post_tolerance_ms: float = DEFAULT_POST_TOLERANCE_MS,
) -> dict[str, Any]:
    active = [d for d in detections if d.score >= threshold]
    used: set[int] = set()
    matches: list[tuple[Truth, Detection, float]] = []

    for t in truth:
        candidates: list[tuple[float, int, Detection]] = []
        lo = t.timestamp_ms - pre_tolerance_ms
        hi = t.timestamp_ms + post_tolerance_ms
        for idx, d in enumerate(active):
            if idx in used:
                continue
            if lo <= d.timestamp_ms <= hi:
                latency = d.timestamp_ms - t.timestamp_ms
                candidates.append((abs(latency), idx, d))
        if candidates:
            _, idx, d = min(candidates, key=lambda x: (x[0], x[2].timestamp_ms))
            used.add(idx)
            matches.append((t, d, d.timestamp_ms - t.timestamp_ms))

    unmatched = [d for idx, d in enumerate(active) if idx not in used]
    matched_truth_ids = {m[0].event_id for m in matches}
    misses = [t for t in truth if t.event_id not in matched_truth_ids]
    return {"matches": matches, "misses": misses, "false_positives": unmatched, "active": active}


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _group_metrics_key(matches: list[tuple[Truth, Detection, float]], misses: list[Truth], key_fn) -> dict[str, Any]:
    groups: dict[str, dict[str, int]] = {}
    for t, _, _ in matches:
        key = key_fn(t) or "unspecified"
        groups.setdefault(key, {"tp": 0, "fn": 0})
        groups[key]["tp"] += 1
    for t in misses:
        key = key_fn(t) or "unspecified"
        groups.setdefault(key, {"tp": 0, "fn": 0})
        groups[key]["fn"] += 1
    out: dict[str, Any] = {}
    for key, counts in sorted(groups.items()):
        n = counts["tp"] + counts["fn"]
        out[key] = {
            **counts,
            "recall": counts["tp"] / n if n else None,
            "miss_rate": counts["fn"] / n if n else None,
        }
    return out


def _group_metrics(matches: list[tuple[Truth, Detection, float]], misses: list[Truth], field: str) -> dict[str, Any]:
    return _group_metrics_key(matches, misses, lambda t: str(getattr(t, field) or "unspecified"))


def _distance_bucket(distance_m: float | None) -> str:
    if distance_m is None:
        return "unspecified"
    if distance_m <= 1.0:
        return "near_0_1m"
    if distance_m <= 3.0:
        return "mid_1_3m"
    return "far_3m_plus"


def _self_tts_bucket(value: bool | None) -> str:
    if value is True:
        return "self_tts"
    if value is False:
        return "not_self_tts"
    return "unspecified"


def evaluate(
    truth: list[Truth],
    detections: list[Detection],
    threshold: float,
    negative_exposure_hours: float,
    pre_tolerance_ms: float = DEFAULT_PRE_TOLERANCE_MS,
    post_tolerance_ms: float = DEFAULT_POST_TOLERANCE_MS,
) -> dict[str, Any]:
    m = match_events(truth, detections, threshold, pre_tolerance_ms, post_tolerance_ms)
    matches = m["matches"]
    misses = m["misses"]
    fps = m["false_positives"]
    tp, fn, fp = len(matches), len(misses), len(fps)
    total = tp + fn
    recall = tp / total if total else None
    miss_rate = fn / total if total else None
    fpph = fp / negative_exposure_hours if negative_exposure_hours > 0 else None
    latencies = [x[2] for x in matches]
    ci_low, ci_high = wilson_interval(tp, total)
    return {
        "threshold": threshold,
        "truth_events": total,
        "detections_at_or_above_threshold": len(m["active"]),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "recall": recall,
        "recall_ci95": [ci_low, ci_high],
        "miss_rate": miss_rate,
        "negative_exposure_hours": negative_exposure_hours,
        "fpph": fpph,
        "false_alarms_per_day": fpph * 24 if fpph is not None else None,
        "fp_rate_ci95": poisson_rate_ci_95(fp, negative_exposure_hours),
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "mean": statistics.fmean(latencies) if latencies else None,
        },
        "by_phrase": _group_metrics(matches, misses, "phrase"),
        "by_speaker": _group_metrics(matches, misses, "speaker"),
        "by_condition": _group_metrics(matches, misses, "condition"),
        "by_room": _group_metrics(matches, misses, "room"),
        "by_background": _group_metrics(matches, misses, "background"),
        "by_distance": _group_metrics_key(matches, misses, lambda t: _distance_bucket(t.distance_m)),
        "by_direction": _group_metrics(matches, misses, "direction"),
        "by_voice_level": _group_metrics(matches, misses, "voice_level"),
        "by_self_tts": _group_metrics_key(matches, misses, lambda t: _self_tts_bucket(t.self_tts)),
        "by_time_bucket": _group_metrics(matches, misses, "time_bucket"),
        "false_positive_timestamps_ms": [d.timestamp_ms for d in fps],
        "missed_event_ids": [t.event_id for t in misses],
    }


def threshold_sweep(
    truth: list[Truth],
    detections: list[Detection],
    thresholds: Iterable[float],
    negative_exposure_hours: float,
    pre_tolerance_ms: float,
    post_tolerance_ms: float,
) -> list[dict[str, Any]]:
    return [
        evaluate(truth, detections, float(t), negative_exposure_hours, pre_tolerance_ms, post_tolerance_ms)
        for t in thresholds
    ]


def parse_thresholds(text: str) -> list[float]:
    vals = sorted({float(x.strip()) for x in text.split(",") if x.strip()})
    if not vals:
        raise ValueError("no thresholds supplied")
    return vals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--truth", required=True, type=Path)
    ap.add_argument("--detections", required=True, type=Path)
    ap.add_argument("--negative-exposure-hours", required=True, type=float)
    ap.add_argument("--thresholds", default="0.05,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9")
    ap.add_argument("--pre-tolerance-ms", type=float, default=DEFAULT_PRE_TOLERANCE_MS)
    ap.add_argument("--post-tolerance-ms", type=float, default=DEFAULT_POST_TOLERANCE_MS)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    truth = load_truth(args.truth)
    detections = load_detections(args.detections)
    report = {
        "schema_version": 1,
        "matching_policy": {
            "one_detection_per_truth_event": True,
            "duplicates_after_first_count_as_false_positive": True,
            "pre_tolerance_ms": args.pre_tolerance_ms,
            "post_tolerance_ms": args.post_tolerance_ms,
        },
        "threshold_sweep": threshold_sweep(
            truth,
            detections,
            parse_thresholds(args.thresholds),
            args.negative_exposure_hours,
            args.pre_tolerance_ms,
            args.post_tolerance_ms,
        ),
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
