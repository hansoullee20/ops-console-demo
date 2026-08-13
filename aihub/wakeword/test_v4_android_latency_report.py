import json
import tempfile
import unittest
from pathlib import Path

from v4_android_latency_report import load_samples, summarize


MODEL_SHA = "a" * 64


def latency_row(
    event_id: str,
    latency_ms: int,
    *,
    session_id: str = "session-1",
    device_model: str = "SM-F936N",
) -> dict:
    onset = 10_000 + int(event_id.rsplit("-", 1)[-1]) * 5_000
    decision = onset + latency_ms
    segment_end = decision - 25
    return {
        "event_id": event_id,
        "kind": "candidate",
        "accepted": True,
        "metadata": {
            "latency_schema_version": 1,
            "latency_definition": "vad_onset_to_decision_monotonic",
            "measurement_clock": "android.os.SystemClock.elapsedRealtime",
            "session_id": session_id,
            "vad_onset_monotonic_ms": onset,
            "segment_end_monotonic_ms": segment_end,
            "decision_monotonic_ms": decision,
            "segment_duration_ms": segment_end - onset,
            "wake_latency_ms": latency_ms,
            "post_segment_processing_ms": 25,
            "device_manufacturer": "samsung",
            "device_model": device_model,
            "device_sdk_int": 36,
            "device_fingerprint": "samsung/q4qksx/q4q:16/test",
            "app_version": "0.2-test",
            "model_name": "template_mfcc_dtw",
            "model_version": "android-v1",
            "model_sha": MODEL_SHA,
        },
    }


class AndroidLatencyReportTests(unittest.TestCase):
    def write_rows(self, rows: list[dict], path: Path) -> None:
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_reports_p50_p95_for_twenty_target_device_events(self):
        rows = [latency_row(f"event-{i}", i * 100) for i in range(1, 21)]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            self.write_rows(rows, path)
            samples, ignored = load_samples(path)
        report = summarize(samples, ignored, min_samples=20)
        self.assertTrue(report["measurement_complete"])
        self.assertEqual(report["sample_count"], 20)
        self.assertEqual(report["wake_latency_ms"]["p50"], 1050.0)
        self.assertEqual(report["wake_latency_ms"]["p95"], 1905.0)
        self.assertEqual(report["target_device"]["model"], "SM-F936N")
        self.assertEqual(report["model"]["sha256"], MODEL_SHA)

    def test_defaults_to_latest_instrumented_session_and_ignores_legacy(self):
        legacy = {"event_id": "legacy", "kind": "candidate", "accepted": True, "metadata": {}}
        rows = [
            latency_row("event-1", 500, session_id="old"),
            legacy,
            latency_row("event-2", 600, session_id="new"),
            latency_row("event-3", 700, session_id="new"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            self.write_rows(rows, path)
            samples, ignored = load_samples(path)
        report = summarize(samples, ignored, min_samples=3)
        self.assertEqual(report["selected_session_id"], "new")
        self.assertEqual(report["sample_count"], 2)
        self.assertFalse(report["measurement_complete"])
        self.assertEqual(report["ignored_uninstrumented_accepted_events"], 1)

    def test_rejects_inconsistent_timestamp_arithmetic(self):
        row = latency_row("event-1", 500)
        row["metadata"]["wake_latency_ms"] = 499
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            self.write_rows([row], path)
            with self.assertRaisesRegex(ValueError, "disagrees with timestamps"):
                load_samples(path)

    def test_rejects_mixed_devices_in_one_session(self):
        rows = [
            latency_row("event-1", 500),
            latency_row("event-2", 600, device_model="different-device"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            self.write_rows(rows, path)
            samples, ignored = load_samples(path)
        with self.assertRaisesRegex(ValueError, "device models"):
            summarize(samples, ignored)

    def test_rejects_non_sha_model_identity(self):
        row = latency_row("event-1", 500)
        row["metadata"]["model_sha"] = "not-a-sha"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "events.jsonl"
            self.write_rows([row], path)
            with self.assertRaisesRegex(ValueError, "lowercase SHA-256"):
                load_samples(path)


if __name__ == "__main__":
    unittest.main()
