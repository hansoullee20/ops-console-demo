import csv
import unittest
from pathlib import Path

from build_v4_scripts import REQUIRED_SCENARIOS, build, validate_rows


class V4ScriptLibraryTests(unittest.TestCase):
    def test_build_is_deterministic_and_valid(self):
        first = build(40)
        second = build(40)
        self.assertEqual(first, second)
        self.assertEqual(validate_rows(first), [])

    def test_required_scenarios_and_languages_are_present(self):
        rows = build(40)
        self.assertEqual({row["scenario"] for row in rows}, REQUIRED_SCENARIOS)
        for scenario in REQUIRED_SCENARIOS:
            self.assertEqual(
                {row["language"] for row in rows if row["scenario"] == scenario},
                {"ko", "en"},
            )

    def test_ids_texts_and_preassigned_splits_are_stable_and_unique(self):
        rows = build(2000)
        self.assertEqual(len({row["script_id"] for row in rows}), len(rows))
        self.assertEqual(
            len({(row["language"], row["normalized_text"]) for row in rows}),
            len(rows),
        )
        self.assertTrue(all(row["id"] == row["script_id"] for row in rows))
        self.assertTrue(all(row["split_group"] == row["script_id"] for row in rows))
        self.assertEqual({row["split"] for row in rows}, {"train", "validation"})

    def test_negative_repeats_is_a_unique_prompt_cap(self):
        rows = build(5)
        ordinary = [row for row in rows if row["scenario"] == "ordinary_negative"]
        self.assertEqual(len(ordinary), 10)
        with self.assertRaisesRegex(ValueError, "must be positive"):
            build(0)

    def test_committed_library_matches_generator(self):
        path = Path(__file__).with_name("v4_scripts.csv")
        with path.open(encoding="utf-8", newline="") as handle:
            committed = list(csv.DictReader(handle))
        self.assertEqual(committed, build(2000))


if __name__ == "__main__":
    unittest.main()
