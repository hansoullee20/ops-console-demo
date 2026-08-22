#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from corpus import LABELS, counts_by, load_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an Okja physical-command PCM corpus")
    parser.add_argument("corpus_dir", type=Path)
    parser.add_argument("--min-per-class", type=int, default=1)
    parser.add_argument("--report-out", type=Path)
    args = parser.parse_args()

    if args.min_per_class < 1:
        parser.error("--min-per-class must be >= 1")

    rows = load_corpus(args.corpus_dir)
    label_counts = counts_by(rows, "label")
    for label in LABELS:
        count = label_counts.get(label, 0)
        if count < args.min_per_class:
            raise SystemExit(
                f"FAIL: {label} has {count} clips; requires >= {args.min_per_class}"
            )

    report = {
        "schema": "okja.physical-command-corpus-validation.v1",
        "valid": True,
        "clips": len(rows),
        "label_counts": label_counts,
        "speaker_counts": counts_by(rows, "speaker_id"),
        "session_counts": counts_by(rows, "session_id"),
        "condition_counts": counts_by(rows, "condition"),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
