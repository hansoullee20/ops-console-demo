import unittest

from v4_dataset_tools import load_manifest_schema, manifest_validation_errors


class V4DatasetManifestTests(unittest.TestCase):
    def _valid_row(self):
        return {
            "clip_id": "clip-001",
            "audio_path": "audio/clip-001.wav",
            "audio_sha256": "a" * 64,
            "language": "ko",
            "label": "positive",
            "text": "옥자",
            "script_id": "script-001",
            "source_id": "melotts_korean",
            "source_license": "MIT",
            "tts_engine": "melotts",
            "tts_engine_version": "0.1.2",
            "voice_id": "KR",
            "generation_seed": "20260812",
            "base_audio_id": "clip-001",
            "split": "test_engine",
            "sample_rate_hz": "16000",
            "channels": "1",
            "duration_ms": "2390",
            "qc_status": "pass",
        }

    def test_complete_provenance_row_passes(self):
        errors = manifest_validation_errors([self._valid_row()], load_manifest_schema())
        self.assertEqual(errors, [])

    def test_missing_source_license_fails(self):
        row = self._valid_row()
        row["source_license"] = ""
        errors = manifest_validation_errors([row], load_manifest_schema())
        self.assertIn("clip-001: missing required field source_license", errors)

    def test_hash_enum_and_numeric_constraints_fail_closed(self):
        row = self._valid_row()
        row["audio_sha256"] = "not-a-hash"
        row["split"] = "dev"
        row["sample_rate_hz"] = "unknown"
        row["peak_abs"] = "nan"
        errors = manifest_validation_errors([row], load_manifest_schema())
        self.assertTrue(any("audio_sha256 does not match" in error for error in errors))
        self.assertIn("clip-001: invalid split 'dev'", errors)
        self.assertIn("clip-001: invalid sample_rate_hz type", errors)
        self.assertIn("clip-001: peak_abs is non-finite", errors)


if __name__ == "__main__":
    unittest.main()
