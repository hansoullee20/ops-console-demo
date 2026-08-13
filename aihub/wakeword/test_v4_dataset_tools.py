import unittest

from v4_dataset_tools import (
    assign_split,
    leakage_errors,
    load_manifest_schema,
    manifest_validation_errors,
)


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

    def test_preassigned_split_is_preserved_before_augmentation(self):
        row = self._valid_row()
        row["holdout_role"] = ""
        row["split"] = "validation"
        self.assertEqual(assign_split(row), "validation")

    def test_conflicting_holdout_and_planned_split_fails(self):
        row = self._valid_row()
        row["holdout_role"] = "engine"
        row["split"] = "train"
        with self.assertRaisesRegex(ValueError, "conflicts with holdout role"):
            assign_split(row)

    def test_normalized_text_and_parent_derivatives_cannot_cross_splits(self):
        base = self._valid_row()
        base.update(
            {
                "clip_id": "base-clean",
                "base_audio_id": "base-family",
                "script_id": "script-clean",
                "template_id": "template-clean",
                "normalized_text": "옥자 불 켜 줘",
                "split": "train",
            }
        )
        augmented = dict(base)
        augmented.update(
            {
                "clip_id": "base-reverb",
                "script_id": "script-reverb",
                "template_id": "template-reverb",
                "augmentation_id": "reverb-1",
                "split": "validation",
            }
        )
        errors = leakage_errors([base, augmented])
        self.assertTrue(any("base leakage base-family" in error for error in errors))
        self.assertTrue(any("normalized text leakage" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
