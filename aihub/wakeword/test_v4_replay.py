import hashlib
import json
import sys
import tempfile
import textwrap
import unittest
import wave
from pathlib import Path

from v4_eval import load_detections
from v4_replay import inspect_wav, replay, write_jsonl


class V4ReplayTests(unittest.TestCase):
    def _write_wav(self, path: Path, sample_rate: int = 16000) -> None:
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            frames = b"\x00\x00" * sample_rate
            wf.writeframes(frames)

    def _write_adapter(self, path: Path, body: str) -> None:
        path.write_text(textwrap.dedent(body), encoding="utf-8")

    def test_replay_pins_hashes_metadata_and_is_eval_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "fixed.wav"
            model = root / "model.onnx"
            adapter = root / "adapter.py"
            self._write_wav(audio)
            model.write_bytes(b"deterministic-model")
            self._write_adapter(
                adapter,
                """
                import json
                print(json.dumps({"timestamp_ms": 900, "score": 0.8}))
                print(json.dumps({"timestamp_ms": 300, "score": 0.7}))
                """,
            )

            rows, manifest = replay(
                audio=audio,
                model=model,
                engine_id="fixture-engine",
                engine_version="1.2.3",
                threshold=0.55,
                adapter_command=[sys.executable, str(adapter), "{audio}", "{model}", "{threshold}"],
                repeats=3,
                audio_source="github-actions:audio-artifact/123",
                model_source="github-actions:model-artifact/456",
                adapter_source="repo@example:aihub/wakeword/adapter.py",
            )

            expected_model_sha = hashlib.sha256(model.read_bytes()).hexdigest()
            self.assertTrue(manifest["deterministic"])
            self.assertEqual(manifest["repeat_count"], 3)
            self.assertEqual(manifest["model_sha256"], expected_model_sha)
            self.assertEqual(manifest["sample_rate_hz"], 16000)
            self.assertEqual(manifest["duration_ms"], 1000)
            self.assertEqual(manifest["audio_source"], "github-actions:audio-artifact/123")
            self.assertEqual(manifest["model_source"], "github-actions:model-artifact/456")
            self.assertEqual(
                manifest["adapter_source"],
                "repo@example:aihub/wakeword/adapter.py",
            )
            self.assertEqual([r["timestamp_ms"] for r in rows], [300.0, 900.0])
            self.assertTrue(all(r["engine"] == "fixture-engine" for r in rows))
            self.assertTrue(all(r["version"] == "1.2.3" for r in rows))
            self.assertTrue(all(r["model"] == expected_model_sha for r in rows))
            self.assertTrue(all(r["threshold"] == 0.55 for r in rows))

            detections_path = root / "detections.jsonl"
            write_jsonl(detections_path, rows)
            detections = load_detections(detections_path)
            self.assertEqual(len(detections), 2)
            self.assertEqual(detections[0].timestamp_ms, 300.0)
            self.assertEqual(detections[0].score, 0.7)

    def test_replay_rejects_nondeterministic_adapter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "fixed.wav"
            model = root / "model.onnx"
            adapter = root / "adapter.py"
            state = root / "state.txt"
            self._write_wav(audio)
            model.write_bytes(b"model")
            self._write_adapter(
                adapter,
                """
                import json
                import pathlib
                import sys
                state = pathlib.Path(sys.argv[1])
                n = int(state.read_text() if state.exists() else "0") + 1
                state.write_text(str(n))
                print(json.dumps({"timestamp_ms": 100, "score": n / 10}))
                """,
            )

            with self.assertRaisesRegex(RuntimeError, "non-deterministic replay"):
                replay(
                    audio=audio,
                    model=model,
                    engine_id="fixture",
                    engine_version="1",
                    threshold=0.5,
                    adapter_command=[sys.executable, str(adapter), str(state)],
                    repeats=2,
                )

    def test_inspect_wav_rejects_wrong_sample_rate(self):
        with tempfile.TemporaryDirectory() as td:
            audio = Path(td) / "bad.wav"
            self._write_wav(audio, sample_rate=8000)
            with self.assertRaisesRegex(ValueError, "16000 Hz"):
                inspect_wav(audio)

    def test_adapter_command_placeholders_are_resolved_without_shell(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            audio = root / "fixed audio.wav"
            model = root / "model file.onnx"
            adapter = root / "adapter.py"
            self._write_wav(audio)
            model.write_bytes(b"model")
            self._write_adapter(
                adapter,
                """
                import json
                import pathlib
                import sys
                audio, model, threshold, engine, version = sys.argv[1:]
                assert pathlib.Path(audio).name == "fixed audio.wav"
                assert pathlib.Path(model).name == "model file.onnx"
                assert threshold == "0.25"
                assert engine == "livekit-v3"
                assert version == "pinned"
                print(json.dumps({"timestamp_ms": 10, "score": 0.9}))
                """,
            )
            rows, _ = replay(
                audio=audio,
                model=model,
                engine_id="livekit-v3",
                engine_version="pinned",
                threshold=0.25,
                adapter_command=[
                    sys.executable,
                    str(adapter),
                    "{audio}",
                    "{model}",
                    "{threshold}",
                    "{engine_id}",
                    "{engine_version}",
                ],
                repeats=2,
            )
            self.assertEqual(rows[0]["timestamp_ms"], 10.0)


if __name__ == "__main__":
    unittest.main()
