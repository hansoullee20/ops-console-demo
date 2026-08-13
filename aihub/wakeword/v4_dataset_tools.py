#!/usr/bin/env python3
"""Okja v4 dataset safety tooling.

Provides deterministic split assignment, leakage checks and WAV QC before any
large synthetic corpus is allowed into training.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import wave
from collections import defaultdict
from pathlib import Path


DEFAULT_MANIFEST_SCHEMA = Path(__file__).with_name("v4_dataset_schema.json")


def stable_bucket(value: str, modulo: int = 10000) -> int:
    h = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") % modulo


def assign_split(row: dict) -> str:
    # Explicit engine/voice holdouts always win. A speaker/engine test split must
    # never be created implicitly, because that can put the same voice/engine in
    # train and a named holdout split and falsely look like valid generalization.
    role = row.get("holdout_role", "").strip()
    role_splits = {
        "engine": "test_engine",
        "speaker": "test_speaker",
        "real": "test_real",
        "household": "test_household",
    }
    planned = row.get("split", "").strip()
    if role:
        if role not in role_splits:
            raise ValueError(f"unknown holdout_role: {role}")
        role_split = role_splits[role]
        if planned and planned != role_split:
            raise ValueError(
                f"planned split {planned!r} conflicts with holdout role {role!r}"
            )
        return role_split
    if planned:
        if planned not in {"train", "validation", "quarantine"}:
            raise ValueError(f"invalid preassigned split without holdout role: {planned}")
        return planned
    # Group by base audio or script so derivatives never cross ordinary splits.
    # Non-holdout synthetic data is only train/validation. Speaker/engine tests
    # are assigned explicitly at corpus-planning time.
    group = row.get("base_audio_id") or row.get("script_id") or row.get("split_group") or row["clip_id"]
    b = stable_bucket(group)
    if b < 8000:
        return "train"
    return "validation"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9A-Za-z가-힣]+", " ", value.lower())).strip()


def load_manifest_schema(path: Path = DEFAULT_MANIFEST_SCHEMA) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_validation_errors(rows: list[dict], schema: dict) -> list[str]:
    """Validate CSV-shaped rows against the enforceable schema constraints.

    CSV values are strings, so this checks required/non-empty fields, enums,
    regex patterns, and scalar numeric types/bounds without adding a second
    runtime dependency solely for smoke-corpus validation.
    """
    if not rows:
        return ["manifest has no rows"]

    errors: list[str] = []
    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for index, row in enumerate(rows, start=2):
        clip = row.get("clip_id", "").strip() or f"CSV row {index}"
        for field in required:
            if not row.get(field, "").strip():
                errors.append(f"{clip}: missing required field {field}")

        for field, rules in properties.items():
            value = row.get(field, "")
            if value == "":
                continue

            allowed = rules.get("enum")
            if allowed is not None and value not in allowed:
                errors.append(f"{clip}: invalid {field} {value!r}")

            pattern = rules.get("pattern")
            if pattern and re.fullmatch(pattern, value) is None:
                errors.append(f"{clip}: {field} does not match {pattern}")

            declared = rules.get("type")
            declared_types = declared if isinstance(declared, list) else [declared]
            numeric_value: float | None = None
            if "string" not in declared_types:
                try:
                    if "integer" in declared_types:
                        numeric_value = float(int(value))
                    elif "number" in declared_types:
                        numeric_value = float(value)
                    elif "boolean" in declared_types and value.lower() not in {
                        "true",
                        "false",
                    }:
                        raise ValueError
                except ValueError:
                    errors.append(f"{clip}: invalid {field} type")
                    continue

            if numeric_value is not None:
                if not math.isfinite(numeric_value):
                    errors.append(f"{clip}: {field} is non-finite")
                    continue
                if "minimum" in rules and numeric_value < rules["minimum"]:
                    errors.append(f"{clip}: {field} is below minimum")
                if "maximum" in rules and numeric_value > rules["maximum"]:
                    errors.append(f"{clip}: {field} is above maximum")

    return errors


def wav_qc(path: Path) -> tuple[dict, list[str]]:
    reasons: list[str] = []
    try:
        with wave.open(str(path), "rb") as w:
            channels = w.getnchannels()
            rate = w.getframerate()
            width = w.getsampwidth()
            frames = w.getnframes()
            raw = w.readframes(frames)
    except Exception as e:
        return {}, [f"unreadable:{type(e).__name__}"]

    duration_ms = int(round(frames * 1000 / rate)) if rate else 0
    if channels != 1:
        reasons.append(f"channels:{channels}")
    if rate != 16000:
        reasons.append(f"sample_rate:{rate}")
    if width != 2:
        reasons.append(f"sample_width:{width}")
    if duration_ms < 250 or duration_ms > 15000:
        reasons.append(f"duration_ms:{duration_ms}")

    peak = rms = silence_fraction = dc_offset = 0.0
    dbfs = float("-inf")
    finite = True
    if width == 2 and raw:
        import array
        samples = array.array("h")
        samples.frombytes(raw)
        if samples:
            scale = 32768.0
            signed = [x / scale for x in samples]
            vals = [abs(v) for v in signed]
            peak = max(vals)
            rms = math.sqrt(sum(v * v for v in signed) / len(signed))
            dc_offset = sum(signed) / len(signed)
            silence_fraction = sum(v < 0.002 for v in vals) / len(vals)
            dbfs = 20.0 * math.log10(rms) if rms > 0 else float("-inf")
            if not all(math.isfinite(v) for v in signed):
                finite = False
                reasons.append("non_finite_samples")
            if peak >= 0.999:
                reasons.append("clipping")
            if rms < 0.001:
                reasons.append("near_silence")
            if silence_fraction > 0.98:
                reasons.append("mostly_silence")
            if abs(dc_offset) > 0.05:
                reasons.append(f"dc_offset:{dc_offset:.6f}")
            if math.isfinite(dbfs) and (dbfs < -50 or dbfs > -3):
                reasons.append(f"loudness_dbfs:{dbfs:.2f}")

    return {
        "sample_rate_hz": rate,
        "channels": channels,
        "duration_ms": duration_ms,
        "peak_abs": round(peak, 6),
        "rms": round(rms, 6),
        "silence_fraction": round(silence_fraction, 6),
        "dc_offset": round(dc_offset, 6),
        "loudness_dbfs": round(dbfs, 3) if math.isfinite(dbfs) else "-inf",
        "finite_samples": str(finite).lower(),
    }, reasons


def leakage_errors(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    by_base: dict[str, set[str]] = defaultdict(set)
    by_template: dict[str, set[str]] = defaultdict(set)
    by_normalized_text: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_audio_hash: dict[str, set[str]] = defaultdict(set)
    ids: set[str] = set()
    for r in rows:
        cid = r.get("clip_id", "")
        if cid in ids:
            errors.append(f"duplicate clip_id: {cid}")
        ids.add(cid)
        split = r.get("split", "")
        base = r.get("base_audio_id") or r.get("script_id") or ""
        if base:
            by_base[base].add(split)
        template = r.get("template_id") or r.get("script_id") or ""
        if template:
            by_template[template].add(split)
        normalized = r.get("normalized_text") or normalize_text(r.get("text", ""))
        if normalized:
            by_normalized_text[(r.get("language", ""), normalized)].add(split)
        audio_hash = r.get("audio_sha256", "").strip()
        if audio_hash:
            by_audio_hash[audio_hash].add(cid)

    for base, splits in by_base.items():
        ordinary = splits & {"train", "validation", "test_speaker", "test_engine"}
        if len(ordinary) > 1:
            errors.append(f"base leakage {base}: {sorted(ordinary)}")
    for template, splits in by_template.items():
        ordinary = splits & {"train", "validation", "test_speaker", "test_engine"}
        if len(ordinary) > 1:
            errors.append(f"template leakage {template}: {sorted(ordinary)}")
    for (language, normalized), splits in by_normalized_text.items():
        ordinary = splits & {"train", "validation", "test_speaker", "test_engine"}
        if len(ordinary) > 1:
            errors.append(
                f"normalized text leakage {language}/{normalized}: {sorted(ordinary)}"
            )
    for audio_hash, clip_ids in by_audio_hash.items():
        if len(clip_ids) > 1:
            errors.append(f"duplicate audio sha256 {audio_hash}: {sorted(clip_ids)}")

    test_engines = {r.get("tts_engine") for r in rows if r.get("split") == "test_engine"}
    train_engines = {r.get("tts_engine") for r in rows if r.get("split") == "train"}
    for eng in sorted((test_engines & train_engines) - {None, ""}):
        errors.append(f"engine holdout leakage: {eng}")

    test_voices = {(r.get("tts_engine"), r.get("voice_id")) for r in rows if r.get("split") == "test_speaker"}
    train_voices = {(r.get("tts_engine"), r.get("voice_id")) for r in rows if r.get("split") == "train"}
    for pair in sorted((test_voices & train_voices) - {(None, None), ("", "")}):
        errors.append(f"speaker holdout leakage: {pair[0]}/{pair[1]}")
    return errors


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(dict.fromkeys(k for r in rows for k in r.keys()))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def cmd_assign(args):
    rows = read_csv(Path(args.input))
    for r in rows:
        r["split"] = assign_split(r)
        r["normalized_text"] = normalize_text(r.get("text", ""))
    write_csv(Path(args.output), rows)
    print(f"assigned splits for {len(rows)} rows -> {args.output}")


def cmd_qc(args):
    rows = read_csv(Path(args.input))
    root = Path(args.audio_root)
    failed = 0
    seen_hashes: dict[str, str] = {}
    for r in rows:
        path = root / r["audio_path"]
        stats, reasons = wav_qc(path)
        r.update({k: str(v) for k, v in stats.items()})
        audio_hash = r.get("audio_sha256", "").strip()
        if audio_hash:
            previous = seen_hashes.get(audio_hash)
            if previous and previous != r.get("clip_id"):
                reasons.append(f"duplicate_audio:{previous}")
            else:
                seen_hashes[audio_hash] = r.get("clip_id", "")
        r["qc_status"] = "fail" if reasons else "pass"
        r["qc_reasons"] = "|".join(reasons)
        failed += bool(reasons)
    write_csv(Path(args.output), rows)
    print(f"QC complete: {len(rows)-failed} pass / {failed} fail")
    if failed and args.fail_on_qc:
        raise SystemExit(2)


def cmd_leakage(args):
    rows = read_csv(Path(args.input))
    errors = leakage_errors(rows)
    has_speaker_holdout = any(r.get("split") == "test_speaker" for r in rows)
    has_engine_holdout = any(r.get("split") == "test_engine" for r in rows)
    print("speaker holdout:", "evaluated" if has_speaker_holdout else "not_evaluable")
    print("engine holdout:", "evaluated" if has_engine_holdout else "not_evaluable")
    if errors:
        print("LEAKAGE CHECK FAILED")
        for e in errors:
            print("-", e)
        raise SystemExit(3)
    print(f"leakage check passed for {len(rows)} rows")


def cmd_validate(args):
    rows = read_csv(Path(args.input))
    errors = manifest_validation_errors(rows, load_manifest_schema(Path(args.schema)))
    if errors:
        print("MANIFEST VALIDATION FAILED")
        for error in errors:
            print("-", error)
        raise SystemExit(4)
    print(f"manifest validation passed for {len(rows)} rows")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("assign-splits")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=cmd_assign)
    p = sub.add_parser("audio-qc")
    p.add_argument("--input", required=True)
    p.add_argument("--audio-root", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--fail-on-qc", action="store_true")
    p.set_defaults(func=cmd_qc)
    p = sub.add_parser("check-leakage")
    p.add_argument("--input", required=True)
    p.set_defaults(func=cmd_leakage)
    p = sub.add_parser("validate-manifest")
    p.add_argument("--input", required=True)
    p.add_argument("--schema", default=str(DEFAULT_MANIFEST_SCHEMA))
    p.set_defaults(func=cmd_validate)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
