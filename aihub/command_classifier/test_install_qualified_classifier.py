from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from corpus import LABELS
from install_qualified_classifier import install, prepare_install


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class QualifiedClassifierInstallerTest(unittest.TestCase):
    def make_output(self, root: Path, *, deployment_allowed: bool = True) -> Path:
        output = root / "training-output"
        output.mkdir()
        model = b"qualified-model-bytes"
        model_hash = sha256(model)
        (output / "physical-command-qualified.tflite").write_bytes(model)
        gate = {
            "passed": deployment_allowed,
            "required_heldout_physical": 3000,
        }
        report = {
            "schema": "okja.physical-command-training.v1",
            "deployment_allowed": deployment_allowed,
            "development_gate": gate,
            "class_order": list(LABELS),
            "model_sha256": model_hash,
            "tensorflow_version": "test",
            "model_parameters": 123,
        }
        thresholds = {
            "schema": "okja.physical-command-thresholds.v1",
            "class_order": list(LABELS),
            "model_sha256": model_hash,
            "min_confidence": 0.8,
            "min_top_two_margin": 0.2,
            "min_opposite_action_margin": 0.4,
            "validation_metrics": {"unsafe_count": 0},
            "test_metrics": {"wrong_action": 0},
        }
        (output / "training-report.json").write_text(json.dumps(report), encoding="utf-8")
        (output / "physical-command-qualified-thresholds.json").write_text(
            json.dumps(thresholds), encoding="utf-8"
        )
        return output

    def test_installs_only_verified_qualified_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = self.make_output(root)
            destination = root / "assets" / "okja-physical-command"

            install(output, destination)

            self.assertEqual(
                b"qualified-model-bytes",
                (destination / "physical-command.tflite").read_bytes(),
            )
            manifest = json.loads((destination / "qualified-manifest.json").read_text())
            self.assertTrue(manifest["deployment_allowed"])
            self.assertEqual(list(LABELS), manifest["class_order"])
            self.assertEqual(0.4, manifest["min_opposite_action_margin"])

    def test_rejects_nonqualified_training_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.make_output(Path(tmp), deployment_allowed=False)
            with self.assertRaises(ValueError):
                prepare_install(output)

    def test_rejects_model_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.make_output(Path(tmp))
            (output / "physical-command-qualified.tflite").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                prepare_install(output)


if __name__ == "__main__":
    unittest.main()
