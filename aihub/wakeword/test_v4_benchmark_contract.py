import argparse
import json
import tempfile
import unittest
from pathlib import Path

from v4_benchmark_contract import (
    make_wake_marker,
    validate_detection,
    validate_jsonl,
    validate_session,
    validate_truth_event,
)


class BenchmarkContractTests(unittest.TestCase):
    def test_test_d_requires_immutable_and_not_training_eligible(self):
        row = {
            "schema_version": 1,
            "benchmark_id": "okja-household-001",
            "recording_id": "livingroom-20260813-001",
            "test_set": "TEST_D",
            "device_id": "fold4-01",
            "room_id": "livingroom",
            "started_at": "2026-08-13T08:00:00+09:00",
            "duration_ms": 3600000,
            "sample_rate_hz": 16000,
            "channels": 1,
            "audio_sha256": "a" * 64,
            "firmware_version": "aihub-voice-test@abc123",
            "app_version": "0.1.0",
            "consent_recorded": True,
            "retention_class": "benchmark_fixed",
            "training_eligible": False,
            "immutable": True,
        }
        validate_session(row)
        broken = dict(row, training_eligible=True)
        with self.assertRaisesRegex(ValueError, "never be training eligible"):
            validate_session(broken)

    def test_truth_and_detection_validate(self):
        truth = {
            "schema_version": 1,
            "event_id": "wake-1",
            "recording_id": "rec-1",
            "timestamp_ms": 1200.0,
            "intentional_invocation": True,
            "phrase": "옥자야",
            "language": "ko-KR",
            "speaker_id": "speaker-a",
            "condition": "normal",
            "room_id": "livingroom",
            "background": "tv",
            "distance_m": 2.0,
            "mention_context": False,
        }
        detection = {
            "schema_version": 1,
            "detection_id": "det-1",
            "recording_id": "rec-1",
            "timestamp_ms": 1320.0,
            "model_name": "okja-v4",
            "model_version": "candidate-1",
            "model_sha": "modelsha",
            "threshold": 0.5,
            "score": 0.81,
            "device_id": "fold4-01",
        }
        validate_truth_event(truth)
        validate_detection(detection)

    def test_marker_writes_evaluator_compatible_truth_row(self):
        args = argparse.Namespace(
            event_id="wake-test",
            recording_id="rec-1",
            timestamp_ms=2500.0,
            phrase="옥자",
            language="ko-KR",
            speaker_id="speaker-a",
            condition="far_field",
            room_id="livingroom",
            background="quiet",
            distance_m=3.0,
            direction="front",
            voice_level="normal",
            mention_context=False,
            notes=None,
        )
        row = make_wake_marker(args)
        self.assertEqual(row["event_id"], "wake-test")
        self.assertEqual(row["phrase"], "옥자")
        self.assertTrue(row["intentional_invocation"])
        validate_truth_event(row)

    def test_jsonl_validation_reports_rows(self):
        row = {
            "schema_version": 1,
            "event_id": "wake-1",
            "recording_id": "rec-1",
            "timestamp_ms": 100.0,
            "intentional_invocation": True,
            "phrase": "옥자",
            "language": "ko-KR",
            "speaker_id": "speaker-a",
            "condition": "normal",
            "room_id": "livingroom",
            "background": "quiet",
            "mention_context": False,
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "truth.jsonl"
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(validate_jsonl(path, "truth"), 1)


if __name__ == "__main__":
    unittest.main()
