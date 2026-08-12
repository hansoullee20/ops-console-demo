import json
import tempfile
import unittest
import wave
from pathlib import Path

from v4_ring_buffer_logger import PcmRingBufferLogger


class RingBufferLoggerTests(unittest.TestCase):
    def test_candidate_saves_exact_pre_and_post_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logger = PcmRingBufferLogger(
                root,
                sample_rate_hz=10,
                pre_seconds=0.3,
                post_seconds=0.2,
            )

            # Five samples enter, but a 3-sample ring must retain only [3,4,5].
            logger.push_pcm16([1, 2, 3, 4, 5])
            self.assertEqual(logger.buffered_samples, 3)

            event_id = logger.capture_candidate(
                score=0.77,
                threshold=0.50,
                accepted=True,
                metadata={"model": "fixture"},
                event_id="candidate-1",
            )
            self.assertEqual(event_id, "candidate-1")
            self.assertEqual(logger.pending_count, 1)

            completed = logger.push_pcm16([6, 7, 8])
            self.assertEqual(len(completed), 1)
            row = completed[0]
            self.assertEqual(row["saved_samples"], 5)
            self.assertEqual(row["score"], 0.77)
            self.assertEqual(row["threshold"], 0.50)
            self.assertTrue(row["accepted"])

            wav_path = root / row["wav_filename"]
            self.assertTrue(wav_path.exists())
            with wave.open(str(wav_path), "rb") as wf:
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getsampwidth(), 2)
                self.assertEqual(wf.getframerate(), 10)
                self.assertEqual(wf.getnframes(), 5)
                frames = wf.readframes(5)
            # PCM16 little-endian: [3,4,5] pre-roll + [6,7] post-roll.
            self.assertEqual(
                frames,
                b"\x03\x00\x04\x00\x05\x00\x06\x00\x07\x00",
            )

    def test_manual_miss_persists_null_model_decision_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logger = PcmRingBufferLogger(
                root,
                sample_rate_hz=10,
                pre_seconds=0.2,
                post_seconds=0.1,
            )
            logger.push_pcm16([11, 12, 13])
            logger.capture_manual_miss(
                metadata={"reason": "user_marked_missed_wake"},
                event_id="miss-1",
            )
            completed = logger.push_pcm16([14])
            self.assertEqual(len(completed), 1)
            row = completed[0]
            self.assertEqual(row["kind"], "manual_miss")
            self.assertIsNone(row["score"])
            self.assertIsNone(row["threshold"])
            self.assertIsNone(row["accepted"])
            self.assertEqual(row["saved_samples"], 3)

    def test_no_audio_is_persisted_without_explicit_capture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logger = PcmRingBufferLogger(
                root,
                sample_rate_hz=10,
                pre_seconds=0.3,
                post_seconds=0.2,
            )
            logger.push_pcm16(list(range(100)))
            self.assertEqual(logger.buffered_samples, 3)
            # TemporaryDirectory itself exists; the logger must not create any
            # durable audio/event files until an explicit candidate/miss capture.
            self.assertEqual(list(root.iterdir()), [])
            self.assertFalse(logger.events_path.exists())

    def test_event_jsonl_has_one_row_per_finalized_capture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logger = PcmRingBufferLogger(
                root,
                sample_rate_hz=10,
                pre_seconds=0.2,
                post_seconds=0.1,
            )
            logger.push_pcm16([1, 2])
            logger.capture_candidate(
                score=0.49,
                threshold=0.50,
                accepted=False,
                event_id="near-1",
            )
            logger.push_pcm16([3])

            lines = logger.events_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            row = json.loads(lines[0])
            self.assertEqual(row["event_id"], "near-1")
            self.assertEqual(row["kind"], "candidate")
            self.assertFalse(row["accepted"])
            self.assertEqual(len(row["audio_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
