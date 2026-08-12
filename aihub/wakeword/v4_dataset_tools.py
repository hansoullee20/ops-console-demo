#!/usr/bin/env python3
"""Okja v4 dataset safety tooling.

Provides deterministic split assignment, leakage checks and WAV QC before any
large synthetic corpus is allowed into training.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import wave
from collections import defaultdict
from pathlib import Path


def stable_bucket(value: str, modulo: int = 10000) -> int:
    h = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") % modulo


def assign_split(row: dict) -> str:
    # Explicit engine/voice holdouts always win.
    role = row.get("holdout_role", "").strip()
    if role == "engine":
        return "test_engine"
    if role == "speaker":
        return "test_speaker"
    if role == "real":
        return "test_real"
    if role == "household":
        return "test_household"
    # Group by base audio or script so derivatives never cross ordinary splits.
    group = row.get("base_audio_id") or row.get("script_id") or row.get("split_group") or row["clip_id"]
    b = stable_bucket(group)
    if b < 8000:
        return "train"
    if b < 9000:
        return "validation"
    return "test_speaker"


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

    peak = rms = silence_fraction = 0.0
    if width == 2 and raw:
        import array
        samples = array.array("h")
        samples.frombytes(raw)
        if samples:
            scale = 32768.0
            vals = [abs(x) / scale for x in samples]
            peak = max(vals)
            rms = math.sqrt(sum(v*v for v in vals) / len(vals))
            silence_fraction = sum(v < 0.002 for v in vals) / len(vals)
            if peak >= 0.999:
                reasons.append("clipping")
            if rms < 0.001:
                reasons.append("near_silence")
            if silence_fraction > 0.98:
                reasons.append("mostly_silence")
    return {
        "sample_rate_hz": rate, "channels": channels, "duration_ms": duration_ms,
        "peak_abs": round(peak, 6), "rms": round(rms, 6),
        "silence_fraction": round(silence_fraction, 6),
    }, reasons


def leakage_errors(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    by_base: dict[str, set[str]] = defaultdict(set)
    by_voice: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_engine: dict[str, set[str]] = defaultdict(set)
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
        eng = r.get("tts_engine", "")
        voice = r.get("voice_id", "")
        if eng and voice:
            by_voice[(eng, voice)].add(split)
        if eng:
            by_engine[eng].add(split)
    for base, splits in by_base.items():
        ordinary = splits & {"train", "validation", "test_speaker", "test_engine"}
        if len(ordinary) > 1:
            errors.append(f"base leakage {base}: {sorted(ordinary)}")
    # Strong holdout checks: test_engine engine cannot appear in train.
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
        w.writeheader(); w.writerows(rows)


def cmd_assign(args):
    rows = read_csv(Path(args.input))
    for r in rows:
        r["split"] = assign_split(r)
    write_csv(Path(args.output), rows)
    print(f"assigned splits for {len(rows)} rows -> {args.output}")


def cmd_qc(args):
    rows = read_csv(Path(args.input)); root = Path(args.audio_root)
    failed = 0
    for r in rows:
        stats, reasons = wav_qc(root / r["audio_path"])
        r.update({k: str(v) for k, v in stats.items()})
        r["qc_status"] = "fail" if reasons else "pass"
        r["qc_reasons"] = "|".join(reasons)
        failed += bool(reasons)
    write_csv(Path(args.output), rows)
    print(f"QC complete: {len(rows)-failed} pass / {failed} fail")
    if failed and args.fail_on_qc:
        raise SystemExit(2)


def cmd_leakage(args):
    rows = read_csv(Path(args.input)); errors = leakage_errors(rows)
    if errors:
        print("LEAKAGE CHECK FAILED")
        for e in errors: print("-", e)
        raise SystemExit(3)
    print(f"leakage check passed for {len(rows)} rows")


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("assign-splits"); p.add_argument("--input", required=True); p.add_argument("--output", required=True); p.set_defaults(func=cmd_assign)
    p = sub.add_parser("audio-qc"); p.add_argument("--input", required=True); p.add_argument("--audio-root", required=True); p.add_argument("--output", required=True); p.add_argument("--fail-on-qc", action="store_true"); p.set_defaults(func=cmd_qc)
    p = sub.add_parser("check-leakage"); p.add_argument("--input", required=True); p.set_defaults(func=cmd_leakage)
    args = ap.parse_args(); args.func(args)

if __name__ == "__main__":
    main()
