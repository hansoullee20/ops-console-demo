#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from corpus import LABELS

MODEL_NAME = "physical-command-qualified.tflite"
THRESHOLDS_NAME = "physical-command-qualified-thresholds.json"
ASSET_MODEL_NAME = "physical-command.tflite"
ASSET_MANIFEST_NAME = "qualified-manifest.json"
MANIFEST_SCHEMA = "okja.physical-command-qualified.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_install(training_output: Path) -> tuple[Path, dict]:
    training_output = training_output.resolve()
    report_path = training_output / "training-report.json"
    model_path = training_output / MODEL_NAME
    thresholds_path = training_output / THRESHOLDS_NAME

    for path in (report_path, model_path, thresholds_path):
        if not path.is_file():
            raise ValueError(f"required qualified artifact missing: {path}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    thresholds = json.loads(thresholds_path.read_text(encoding="utf-8"))

    if report.get("deployment_allowed") is not True:
        raise ValueError("training report does not permit deployment")
    gate = report.get("development_gate") or {}
    if gate.get("passed") is not True:
        raise ValueError("development gate is not passed")

    class_order = report.get("class_order")
    if class_order != list(LABELS):
        raise ValueError(f"unexpected report class order: {class_order}")
    if thresholds.get("class_order") != list(LABELS):
        raise ValueError("threshold class order does not match runtime contract")

    model_hash = sha256(model_path)
    expected_hashes = {
        str(report.get("model_sha256", "")).lower(),
        str(thresholds.get("model_sha256", "")).lower(),
    }
    if expected_hashes != {model_hash}:
        raise ValueError(
            f"qualified model SHA mismatch: actual={model_hash}, expected={sorted(expected_hashes)}"
        )

    required_thresholds = (
        "min_confidence",
        "min_top_two_margin",
        "min_opposite_action_margin",
    )
    values = {}
    for key in required_thresholds:
        if key not in thresholds:
            raise ValueError(f"threshold record missing {key}")
        value = float(thresholds[key])
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{key} must be in [0, 1]")
        values[key] = value

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "deployment_allowed": True,
        "model_file": ASSET_MODEL_NAME,
        "model_sha256": model_hash,
        "class_order": list(LABELS),
        **values,
        "development_gate": gate,
        "validation_metrics": thresholds.get("validation_metrics"),
        "test_metrics": thresholds.get("test_metrics"),
        "source_training_schema": report.get("schema"),
        "tensorflow_version": report.get("tensorflow_version"),
        "model_parameters": report.get("model_parameters"),
        "model_bytes": model_path.stat().st_size,
    }
    return model_path, manifest


def install(training_output: Path, asset_dir: Path) -> None:
    model_path, manifest = prepare_install(training_output)
    asset_dir = asset_dir.resolve()
    asset_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="okja-qualified-install-", dir=asset_dir.parent) as tmp:
        staging = Path(tmp)
        shutil.copy2(model_path, staging / ASSET_MODEL_NAME)
        (staging / ASSET_MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        if asset_dir.exists():
            if not asset_dir.is_dir():
                raise ValueError(f"asset destination is not a directory: {asset_dir}")
            shutil.rmtree(asset_dir)
        shutil.copytree(staging, asset_dir)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install only a safety-qualified Okja physical-command model into Android assets"
    )
    parser.add_argument("training_output", type=Path)
    parser.add_argument(
        "--asset-dir",
        type=Path,
        default=Path("aihub/app/src/main/assets/okja-physical-command"),
    )
    args = parser.parse_args()

    install(args.training_output, args.asset_dir)
    print(f"installed qualified classifier into {args.asset_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
