import unittest

from v4_eval import Detection, Truth, evaluate, parse_thresholds


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

    def test_threshold_parse_is_sorted_unique(self):
        self.assertEqual(parse_thresholds("0.5,0.1,0.5"), [0.1, 0.5])


if __name__ == "__main__":
    unittest.main()
