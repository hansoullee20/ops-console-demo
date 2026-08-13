import json
import tempfile
import unittest
from pathlib import Path

from v4_eval import Detection, Truth, evaluate, load_truth, parse_thresholds, threshold_sweep


class V4EvalTests(unittest.TestCase):
    def setUp(self):
        self.truth = [
            Truth("a", 1000, phrase="옥자", speaker="s1", condition="quiet", room="living", background="none"),
            Truth("b", 5000, phrase="옥자야", speaker="s2", condition="tv", room="living", background="tv"),
        ]
        self.dets = [
            Detection(1100, 0.90),
            Detection(1200, 0.80),  # duplicate around a -> FP
            Detection(5200, 0.70),
            Detection(9000, 0.95),  # unmatched -> FP
        ]

    def test_one_to_one_and_duplicate_fp(self):
        r = evaluate(self.truth, self.dets, 0.5, negative_exposure_hours=2.0)
        self.assertEqual(r["tp"], 2)
        self.assertEqual(r["fn"], 0)
        self.assertEqual(r["fp"], 2)
        self.assertAlmostEqual(r["recall"], 1.0)
        self.assertAlmostEqual(r["fpph"], 1.0)
        self.assertAlmostEqual(r["false_alarms_per_day"], 24.0)
        self.assertEqual(r["latency_ms"]["p50"], 150.0)

    def test_threshold_changes_recall(self):
        r = evaluate(self.truth, self.dets, 0.85, negative_exposure_hours=2.0)
        self.assertEqual(r["tp"], 1)
        self.assertEqual(r["fn"], 1)
        self.assertEqual(r["fp"], 1)
        self.assertAlmostEqual(r["recall"], 0.5)

    def test_zero_fp_has_nonzero_upper_confidence_bound(self):
        r = evaluate([self.truth[0]], [Detection(1050, 0.9)], 0.5, negative_exposure_hours=24.0)
        self.assertEqual(r["fp"], 0)
        self.assertEqual(r["fp_rate_ci95"]["lower_per_hour"], 0.0)
        self.assertGreater(r["fp_rate_ci95"]["upper_per_hour"], 0.0)

    def test_group_breakdown(self):
        r = evaluate(self.truth, self.dets, 0.85, negative_exposure_hours=2.0)
        self.assertAlmostEqual(r["by_phrase"]["옥자"]["recall"], 1.0)
        self.assertAlmostEqual(r["by_phrase"]["옥자야"]["recall"], 0.0)
        self.assertAlmostEqual(r["by_condition"]["quiet"]["recall"], 1.0)
        self.assertAlmostEqual(r["by_condition"]["tv"]["recall"], 0.0)

    def test_benchmark_metadata_fallbacks_and_extended_breakdowns(self):
        row = {
            "event_id": "meta",
            "timestamp_ms": 1000,
            "intentional_invocation": True,
            "phrase": "옥자",
            "speaker_id": "grandma",
            "condition": "far_field",
            "room_id": "livingroom",
            "background": "tv_noise",
            "distance_m": 4.2,
            "direction": "back",
            "voice_level": "soft",
            "self_tts": True,
            "time_bucket": "night",
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "truth.jsonl"
            p.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            truth = load_truth(p)
        r = evaluate(truth, [Detection(1100, 0.9)], 0.5, negative_exposure_hours=1.0)
        self.assertIn("grandma", r["by_speaker"])
        self.assertIn("livingroom", r["by_room"])
        self.assertIn("tv_noise", r["by_background"])
        self.assertIn("far_3m_plus", r["by_distance"])
        self.assertIn("back", r["by_direction"])
        self.assertIn("soft", r["by_voice_level"])
        self.assertIn("self_tts", r["by_self_tts"])
        self.assertIn("night", r["by_time_bucket"])

    def test_threshold_sweep_is_automatic_and_ordered(self):
        rows = threshold_sweep(self.truth, self.dets, [0.5, 0.85], 2.0, 500, 1500)
        self.assertEqual([r["threshold"] for r in rows], [0.5, 0.85])
        self.assertGreater(rows[0]["recall"], rows[1]["recall"])

    def test_threshold_parse_is_sorted_unique(self):
        self.assertEqual(parse_thresholds("0.5,0.1,0.5"), [0.1, 0.5])


if __name__ == "__main__":
    unittest.main()
