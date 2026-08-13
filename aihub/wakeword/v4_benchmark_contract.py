#!/usr/bin/env python3
"""Okja v4 household benchmark contract + intentional-wake marker.

Uses only the Python standard library so the validation/marker path can run on
CI, Android/Termux, or a laptop without adding runtime dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GITLIKE_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")
TEST_SETS = {"TEST_A", "TEST_B", "TEST_C", "TEST_D"}
RETENTION_CLASSES = {"benchmark_fixed", "diagnostic_short", "temporary"}


def _require(row: dict[str, Any], fields: list[str], kind: str) -> None:
    missing = [field for field in fields if field not in row]
    if missing:
        raise ValueError(f"{kind}: missing required fields: {', '.join(missing)}")


def _nonempty(row: dict[str, Any], fields: list[str], kind: str) -> None:
    for field in fields:
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ValueError(f"{kind}: {field} must be a non-empty string")


def _validate_datetime(value: str, kind: str, field: str) -> None:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{kind}: {field} must be an ISO-8601 date-time") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{kind}: {field} must include a timezone offset")


def validate_session(row: dict[str, Any]) -> None:
    kind = "session"
    required = [
        "schema_version", "benchmark_id", "recording_id", "test_set",
        "device_id", "room_id", "started_at", "duration_ms",
        "audio_filename", "sample_rate_hz", "channels", "audio_sha256",
        "firmware_version", "firmware_git_sha", "app_version", "model_sha",
        "consent_recorded", "retention_class", "training_eligible",
    ]
    _require(row, required, kind)
    _nonempty(row, [
        "benchmark_id", "recording_id", "device_id", "room_id",
        "started_at", "audio_filename", "firmware_version",
        "firmware_git_sha", "app_version", "model_sha",
    ], kind)
    if row["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"{kind}: schema_version must be {SCHEMA_VERSION}")
    _validate_datetime(row["started_at"], kind, "started_at")
    if row["test_set"] not in TEST_SETS:
        raise ValueError(f"{kind}: invalid test_set {row['test_set']!r}")
    if not isinstance(row["duration_ms"], int) or row["duration_ms"] <= 0:
        raise ValueError(f"{kind}: duration_ms must be a positive integer")
    filename = row["audio_filename"]
    if "/" in filename or "\\" in filename or not filename.endswith(".wav"):
        raise ValueError(f"{kind}: audio_filename must be a basename ending in .wav")
    for token_field in ("device_id", "room_id", "recording_id"):
        if row[token_field] not in filename:
            raise ValueError(f"{kind}: audio_filename must include {token_field}")
    if not isinstance(row["sample_rate_hz"], int) or row["sample_rate_hz"] < 8000:
        raise ValueError(f"{kind}: sample_rate_hz must be >= 8000")
    if not isinstance(row["channels"], int) or not (1 <= row["channels"] <= 8):
        raise ValueError(f"{kind}: channels must be 1..8")
    if not isinstance(row["audio_sha256"], str) or not SHA256_RE.match(row["audio_sha256"]):
        raise ValueError(f"{kind}: audio_sha256 must be lowercase 64-char SHA-256")
    for sha_field in ("firmware_git_sha", "model_sha"):
        if not GITLIKE_SHA_RE.match(row[sha_field]):
            raise ValueError(f"{kind}: {sha_field} must be 7..64 lowercase hex chars")
    if row["consent_recorded"] is not True:
        raise ValueError(f"{kind}: consent_recorded must be true")
    if row["retention_class"] not in RETENTION_CLASSES:
        raise ValueError(f"{kind}: invalid retention_class")
    if not isinstance(row["training_eligible"], bool):
        raise ValueError(f"{kind}: training_eligible must be boolean")
    if row["test_set"] == "TEST_D":
        if row["training_eligible"] is not False:
            raise ValueError("session: TEST_D must never be training eligible")
        if row.get("immutable") is not True:
            raise ValueError("session: TEST_D must set immutable=true")
        if row["retention_class"] != "benchmark_fixed":
            raise ValueError("session: TEST_D retention_class must be benchmark_fixed")


def validate_truth_event(row: dict[str, Any]) -> None:
    kind = "truth"
    required = [
        "schema_version", "event_id", "recording_id", "timestamp_ms",
        "intentional_invocation", "phrase", "language", "speaker_id",
        "condition", "room_id", "background", "mention_context",
    ]
    _require(row, required, kind)
    _nonempty(row, [
        "event_id", "recording_id", "phrase", "language", "speaker_id",
        "condition", "room_id", "background",
    ], kind)
    if row["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"{kind}: schema_version must be {SCHEMA_VERSION}")
    if not isinstance(row["timestamp_ms"], (int, float)) or row["timestamp_ms"] < 0:
        raise ValueError(f"{kind}: timestamp_ms must be >= 0")
    if row["intentional_invocation"] is not True:
        raise ValueError(f"{kind}: intentional_invocation must be true")
    if not isinstance(row["mention_context"], bool):
        raise ValueError(f"{kind}: mention_context must be boolean")
    if row.get("distance_m") is not None:
        if not isinstance(row["distance_m"], (int, float)) or row["distance_m"] < 0:
            raise ValueError(f"{kind}: distance_m must be null or >= 0")
    if "self_tts" in row and not isinstance(row["self_tts"], bool):
        raise ValueError(f"{kind}: self_tts must be boolean")
    if row.get("time_bucket") not in (None, "day", "night"):
        raise ValueError(f"{kind}: time_bucket must be day or night")


def validate_detection(row: dict[str, Any]) -> None:
    kind = "detection"
    required = [
        "schema_version", "detection_id", "recording_id", "timestamp_ms",
        "model_name", "model_version", "model_sha", "threshold", "score",
        "device_id",
    ]
    _require(row, required, kind)
    _nonempty(row, [
        "detection_id", "recording_id", "model_name", "model_version",
        "model_sha", "device_id",
    ], kind)
    if row["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"{kind}: schema_version must be {SCHEMA_VERSION}")
    if not isinstance(row["timestamp_ms"], (int, float)) or row["timestamp_ms"] < 0:
        raise ValueError(f"{kind}: timestamp_ms must be >= 0")
    if not GITLIKE_SHA_RE.match(row["model_sha"]):
        raise ValueError(f"{kind}: model_sha must be 7..64 lowercase hex chars")
    for field in ("threshold", "score"):
        if not isinstance(row[field], (int, float)):
            raise ValueError(f"{kind}: {field} must be numeric")


VALIDATORS = {
    "session": validate_session,
    "truth": validate_truth_event,
    "detection": validate_detection,
}


def validate_jsonl(path: Path, kind: str) -> int:
    validator = VALIDATORS[kind]
    count = 0
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
                if not isinstance(row, dict):
                    raise ValueError("row must be a JSON object")
                validator(row)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"{path}:{lineno}: {exc}") from exc
            count += 1
    return count


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_wake_marker(args: argparse.Namespace) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA_VERSION,
        "event_id": args.event_id or f"wake-{uuid.uuid4()}",
        "recording_id": args.recording_id,
        "timestamp_ms": args.timestamp_ms,
        "intentional_invocation": True,
        "phrase": args.phrase,
        "language": args.language,
        "speaker_id": args.speaker_id,
        "condition": args.condition,
        "room_id": args.room_id,
        "background": args.background,
        "distance_m": args.distance_m,
        "direction": args.direction,
        "voice_level": args.voice_level,
        "self_tts": bool(getattr(args, "self_tts", False)),
        "mention_context": args.mention_context,
        "marked_at": datetime.now(timezone.utc).isoformat(),
        "notes": args.notes or "",
    }
    time_bucket = getattr(args, "time_bucket", None)
    if time_bucket is not None:
        row["time_bucket"] = time_bucket
    validate_truth_event(row)
    return row


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    val = sub.add_parser("validate", help="validate a benchmark JSONL file")
    val.add_argument("kind", choices=sorted(VALIDATORS))
    val.add_argument("path", type=Path)

    mark = sub.add_parser("mark-wake", help="append one intentional wake event")
    mark.add_argument("--output", type=Path, required=True)
    mark.add_argument("--recording-id", required=True)
    mark.add_argument("--timestamp-ms", type=float, required=True)
    mark.add_argument("--phrase", required=True)
    mark.add_argument("--language", default="ko-KR")
    mark.add_argument("--speaker-id", required=True)
    mark.add_argument("--condition", default="normal")
    mark.add_argument("--room-id", required=True)
    mark.add_argument("--background", default="quiet")
    mark.add_argument("--distance-m", type=float)
    mark.add_argument("--direction")
    mark.add_argument("--voice-level")
    mark.add_argument("--self-tts", action="store_true")
    mark.add_argument("--time-bucket", choices=["day", "night"])
    mark.add_argument("--mention-context", action="store_true")
    mark.add_argument("--event-id")
    mark.add_argument("--notes")
    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "validate":
            count = validate_jsonl(args.path, args.kind)
            print(json.dumps({"status": "ok", "kind": args.kind, "rows": count}))
            return
        if args.command == "mark-wake":
            row = make_wake_marker(args)
            append_jsonl(args.output, row)
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))
            return
        raise AssertionError(args.command)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
