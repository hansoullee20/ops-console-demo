import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from openwakeword_replay_adapter import (
    DEFAULT_FRAME_SAMPLES,
    replay_stream,
    replay_wav,
    require_openwakeword_version,
)


class OpenWakeWordReplayAdapterTests(unittest.TestCase):
    def _write_wav(self, path: Path, *, frame_count: int) -> None:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * frame_count)

    def test_streams_exact_frames_and_applies_debounce(self):
        samples = [0] * (DEFAULT_FRAME_SAMPLES * 30)
        seen_frames = []

        def predict(frame):
            seen_frames.append(frame)
            return {"okja_v3": 0.9}

        rows = replay_stream(
            samples,
            model_name="okja_v3",
            threshold=0.5,
            predictor=predict,
        )

        self.assertEqual([row["timestamp_ms"] for row in rows], [80.0, 2080.0])
        self.assertEqual(len(seen_frames), 30)
        self.assertTrue(all(len(frame) == DEFAULT_FRAME_SAMPLES for frame in seen_frames))

    def test_partial_final_frame_is_not_replayed(self):
        calls = []
        replay_stream(
            [0] * (DEFAULT_FRAME_SAMPLES * 2 + 17),
            model_name="okja_v3",
            threshold=1.0,
            predictor=lambda frame: calls.append(frame) or {"okja_v3": 0.0},
        )
        self.assertEqual(len(calls), 2)

    def test_replay_wav_defaults_model_name_to_onnx_stem(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "fixed.wav"
            model = root / "okja_v3.onnx"
            melspec = root / "melspectrogram.onnx"
            embedding = root / "embedding_model.onnx"
            self._write_wav(audio, frame_count=DEFAULT_FRAME_SAMPLES)
            model.write_bytes(b"fixture")
            melspec.write_bytes(b"fixture")
            embedding.write_bytes(b"fixture")
            seen_paths = []

            def factory(model_path, melspec_path, embedding_path):
                seen_paths.append((model_path, melspec_path, embedding_path))
                return lambda _frame: {"okja_v3": 0.75}

            rows = replay_wav(
                audio_path=audio,
                model_path=model,
                melspec_model_path=melspec,
                embedding_model_path=embedding,
                model_name=None,
                threshold=0.5,
                predictor_factory=factory,
            )

            self.assertEqual(seen_paths, [(model, melspec, embedding)])
            self.assertEqual(rows[0]["model_name"], "okja_v3")

    def test_missing_feature_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "fixed.wav"
            model = root / "okja_v3.onnx"
            embedding = root / "embedding_model.onnx"
            self._write_wav(audio, frame_count=DEFAULT_FRAME_SAMPLES)
            model.write_bytes(b"fixture")
            embedding.write_bytes(b"fixture")

            with self.assertRaisesRegex(ValueError, "melspectrogram model"):
                replay_wav(
                    audio_path=audio,
                    model_path=model,
                    melspec_model_path=root / "missing.onnx",
                    embedding_model_path=embedding,
                    model_name=None,
                    threshold=0.5,
                    predictor_factory=lambda *_paths: lambda _frame: {},
                )

    def test_missing_or_non_finite_score_fails_closed(self):
        samples = [0] * DEFAULT_FRAME_SAMPLES
        with self.assertRaisesRegex(RuntimeError, "did not contain model"):
            replay_stream(
                samples,
                model_name="okja_v3",
                threshold=0.5,
                predictor=lambda _frame: {"other": 0.9},
            )
        with self.assertRaisesRegex(RuntimeError, "non-finite"):
            replay_stream(
                samples,
                model_name="okja_v3",
                threshold=0.5,
                predictor=lambda _frame: {"okja_v3": float("nan")},
            )

    def test_invalid_threshold_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"\[0, 1\]"):
            replay_stream(
                [0] * DEFAULT_FRAME_SAMPLES,
                model_name="okja_v3",
                threshold=1.1,
                predictor=lambda _frame: {"okja_v3": 0.0},
            )

    @mock.patch("openwakeword_replay_adapter.metadata.version", return_value="0.6.0")
    def test_engine_version_must_match_exactly(self, _version):
        self.assertEqual(require_openwakeword_version("0.6.0"), "0.6.0")
        with self.assertRaisesRegex(RuntimeError, "version mismatch"):
            require_openwakeword_version("0.5.1")


if __name__ == "__main__":
    unittest.main()
