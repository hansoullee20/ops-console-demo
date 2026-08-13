import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from livekit_v3_replay_adapter import (
    DEFAULT_FRAME_SAMPLES,
    load_pcm16_wav,
    replay_pcm,
    replay_wav,
    require_livekit_version,
)


class LiveKitV3ReplayAdapterTests(unittest.TestCase):
    def _write_wav(
        self,
        path: Path,
        *,
        frame_count: int,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00\x00" * frame_count * channels)

    def test_constant_high_score_matches_listener_window_and_reset(self):
        samples = [0] * (DEFAULT_FRAME_SAMPLES * 62)
        windows = []

        def predict(window):
            windows.append(window)
            return {"okja_v3": 0.9}

        rows = replay_pcm(
            samples,
            model_name="okja_v3",
            threshold=0.5,
            predictor=predict,
        )

        self.assertEqual([row["timestamp_ms"] for row in rows], [2000.0, 4000.0])
        self.assertTrue(all(row["score"] == 0.9 for row in rows))
        self.assertTrue(all(len(window) == 32000 for window in windows))

    def test_sliding_window_emits_first_threshold_crossing(self):
        samples = [0] * (DEFAULT_FRAME_SAMPLES * 27)
        scores = iter([0.2, 0.8, 0.9])

        rows = replay_pcm(
            samples,
            model_name="okja_v3",
            threshold=0.5,
            predictor=lambda _window: {"okja_v3": next(scores)},
        )

        self.assertEqual(
            rows,
            [{"timestamp_ms": 2080.0, "score": 0.8, "model_name": "okja_v3"}],
        )

    def test_replay_wav_defaults_model_name_to_onnx_stem(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "fixed.wav"
            model = root / "okja_v3.onnx"
            self._write_wav(audio, frame_count=DEFAULT_FRAME_SAMPLES * 25)
            model.write_bytes(b"fixture")
            seen_model_paths = []

            def factory(model_path):
                seen_model_paths.append(model_path)
                return lambda _window: {"okja_v3": 0.75}

            rows = replay_wav(
                audio_path=audio,
                model_path=model,
                model_name=None,
                threshold=0.5,
                predictor_factory=factory,
            )

            self.assertEqual(seen_model_paths, [model])
            self.assertEqual(rows[0]["model_name"], "okja_v3")

    def test_missing_model_score_fails_closed(self):
        samples = [0] * (DEFAULT_FRAME_SAMPLES * 25)
        with self.assertRaisesRegex(RuntimeError, "did not contain model"):
            replay_pcm(
                samples,
                model_name="okja_v3",
                threshold=0.5,
                predictor=lambda _window: {"other": 0.9},
            )

    def test_invalid_threshold_and_wav_format_are_rejected(self):
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            replay_pcm(
                [0] * 32000,
                model_name="okja_v3",
                threshold=float("nan"),
                predictor=lambda _window: {"okja_v3": 0.9},
            )

        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "bad.wav"
            self._write_wav(audio, frame_count=8000, sample_rate=8000)
            with self.assertRaisesRegex(ValueError, "16000 Hz"):
                load_pcm16_wav(audio)

    @mock.patch("livekit_v3_replay_adapter.metadata.version", return_value="0.1.2")
    def test_engine_version_must_match_exactly(self, _version):
        self.assertEqual(require_livekit_version("0.1.2"), "0.1.2")
        with self.assertRaisesRegex(RuntimeError, "version mismatch"):
            require_livekit_version("0.1.1")


if __name__ == "__main__":
    unittest.main()
