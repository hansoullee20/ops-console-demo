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
            "audio_filename": "20260813T080000Z__fold4-01__livingroom__livingroom-20260813-001.wav",
            "sample_rate_hz": 16000,
            "channels": 1,
            "audio_sha256": "a" * 64,
            "firmware_version": "0.1.0",
            "firmware_git_sha": "abcdef1",
            "app_version": "0.1.0",
            "model_sha": "1234567",
            "consent_recorded": True,
            "retention_class": "benchmark_fixed",
            "training_eligible": False,
            "immutable": True,
        }
        validate_session(row)
        broken = dict(row, training_eligible=True)
        with self.assertRaisesRegex(ValueError, "never be training eligible"):
            validate_session(broken)
        bad_name = dict(row, audio_filename="capture.wav")
        with self.assertRaisesRegex(ValueError, "must include device_id"):
            validate_session(bad_name)
        bad_timestamp = dict(row, started_at="2026-08-13T08:00:00")
        with self.assertRaisesRegex(ValueError, "timezone offset"):
            validate_session(bad_timestamp)
        malformed_timestamp = dict(row, started_at="not-a-time")
        with self.assertRaisesRegex(ValueError, "ISO-8601"):
            validate_session(malformed_timestamp)

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
            "model_sha": "abcdef1",
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
            self_tts=True,
            time_bucket="night",
            mention_context=False,
            notes=None,
        )
        row = make_wake_marker(args)
        self.assertEqual(row["event_id"], "wake-test")
        self.assertEqual(row["phrase"], "옥자")
        self.assertTrue(row["intentional_invocation"])
        self.assertTrue(row["self_tts"])
        self.assertEqual(row["time_bucket"], "night")
        validate_truth_event(row)
        with self.assertRaisesRegex(ValueError, "self_tts must be boolean"):
            validate_truth_event(dict(row, self_tts="yes"))
        with self.assertRaisesRegex(ValueError, "time_bucket must be day or night"):
            validate_truth_event(dict(row, time_bucket="dusk"))

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
