import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAKE = ROOT / "aihub" / "wakeword"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_eval() -> None:
    path = WAKE / "v4_eval.py"
    s = path.read_text(encoding="utf-8")
    s = replace_once(
        s,
        '    background: str = ""\n\n\n@dataclass(frozen=True)\nclass Detection:\n',
        '    background: str = ""\n    distance_m: float | None = None\n    direction: str = ""\n    voice_level: str = ""\n    self_tts: bool | None = None\n    time_bucket: str = ""\n\n\n@dataclass(frozen=True)\nclass Detection:\n',
        "Truth fields",
    )
    s = replace_once(
        s,
        '                phrase=str(row.get("phrase", "")),\n                speaker=str(row.get("speaker", "")),\n                condition=str(row.get("condition", "")),\n                room=str(row.get("room", "")),\n                background=str(row.get("background", "")),\n',
        '                phrase=str(row.get("phrase", "")),\n                speaker=str(row.get("speaker", row.get("speaker_id", ""))),\n                condition=str(row.get("condition", "")),\n                room=str(row.get("room", row.get("room_id", ""))),\n                background=str(row.get("background", "")),\n                distance_m=(float(row["distance_m"]) if row.get("distance_m") is not None else None),\n                direction=str(row.get("direction", "")),\n                voice_level=str(row.get("voice_level", "")),\n                self_tts=(row.get("self_tts") if isinstance(row.get("self_tts"), bool) else None),\n                time_bucket=str(row.get("time_bucket", "")),\n',
        "truth loader",
    )
    old_group = '''def _group_metrics(matches: list[tuple[Truth, Detection, float]], misses: list[Truth], field: str) -> dict[str, Any]:
    groups: dict[str, dict[str, int]] = {}
    for t, _, _ in matches:
        key = getattr(t, field) or "unspecified"
        groups.setdefault(key, {"tp": 0, "fn": 0})
        groups[key]["tp"] += 1
    for t in misses:
        key = getattr(t, field) or "unspecified"
        groups.setdefault(key, {"tp": 0, "fn": 0})
        groups[key]["fn"] += 1
    out: dict[str, Any] = {}
    for key, counts in sorted(groups.items()):
        n = counts["tp"] + counts["fn"]
        out[key] = {
            **counts,
            "recall": counts["tp"] / n if n else None,
            "miss_rate": counts["fn"] / n if n else None,
        }
    return out


'''
    new_group = '''def _group_metrics_key(matches: list[tuple[Truth, Detection, float]], misses: list[Truth], key_fn) -> dict[str, Any]:
    groups: dict[str, dict[str, int]] = {}
    for t, _, _ in matches:
        key = key_fn(t) or "unspecified"
        groups.setdefault(key, {"tp": 0, "fn": 0})
        groups[key]["tp"] += 1
    for t in misses:
        key = key_fn(t) or "unspecified"
        groups.setdefault(key, {"tp": 0, "fn": 0})
        groups[key]["fn"] += 1
    out: dict[str, Any] = {}
    for key, counts in sorted(groups.items()):
        n = counts["tp"] + counts["fn"]
        out[key] = {
            **counts,
            "recall": counts["tp"] / n if n else None,
            "miss_rate": counts["fn"] / n if n else None,
        }
    return out


def _group_metrics(matches: list[tuple[Truth, Detection, float]], misses: list[Truth], field: str) -> dict[str, Any]:
    return _group_metrics_key(matches, misses, lambda t: str(getattr(t, field) or "unspecified"))


def _distance_bucket(distance_m: float | None) -> str:
    if distance_m is None:
        return "unspecified"
    if distance_m <= 1.0:
        return "near_0_1m"
    if distance_m <= 3.0:
        return "mid_1_3m"
    return "far_3m_plus"


def _self_tts_bucket(value: bool | None) -> str:
    if value is True:
        return "self_tts"
    if value is False:
        return "not_self_tts"
    return "unspecified"


'''
    s = replace_once(s, old_group, new_group, "group helpers")
    s = replace_once(
        s,
        '        "by_background": _group_metrics(matches, misses, "background"),\n        "false_positive_timestamps_ms": [d.timestamp_ms for d in fps],\n',
        '        "by_background": _group_metrics(matches, misses, "background"),\n        "by_distance": _group_metrics_key(matches, misses, lambda t: _distance_bucket(t.distance_m)),\n        "by_direction": _group_metrics(matches, misses, "direction"),\n        "by_voice_level": _group_metrics(matches, misses, "voice_level"),\n        "by_self_tts": _group_metrics_key(matches, misses, lambda t: _self_tts_bucket(t.self_tts)),\n        "by_time_bucket": _group_metrics(matches, misses, "time_bucket"),\n        "false_positive_timestamps_ms": [d.timestamp_ms for d in fps],\n',
        "report groups",
    )
    path.write_text(s, encoding="utf-8")


def patch_schema_contract() -> None:
    schema_path = WAKE / "v4_benchmark_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    props = schema["$defs"]["truth_event"]["properties"]
    props["self_tts"] = {"type": "boolean"}
    props["time_bucket"] = {"type": "string", "enum": ["day", "night"]}
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    path = WAKE / "v4_benchmark_contract.py"
    c = path.read_text(encoding="utf-8")
    c = replace_once(
        c,
        '    if row.get("distance_m") is not None:\n        if not isinstance(row["distance_m"], (int, float)) or row["distance_m"] < 0:\n            raise ValueError(f"{kind}: distance_m must be null or >= 0")\n\n\n',
        '    if row.get("distance_m") is not None:\n        if not isinstance(row["distance_m"], (int, float)) or row["distance_m"] < 0:\n            raise ValueError(f"{kind}: distance_m must be null or >= 0")\n    if "self_tts" in row and not isinstance(row["self_tts"], bool):\n        raise ValueError(f"{kind}: self_tts must be boolean")\n    if row.get("time_bucket") not in (None, "day", "night"):\n        raise ValueError(f"{kind}: time_bucket must be day or night")\n\n\n',
        "truth metadata validation",
    )
    c = replace_once(
        c,
        '        "voice_level": args.voice_level,\n        "mention_context": args.mention_context,\n',
        '        "voice_level": args.voice_level,\n        "self_tts": bool(getattr(args, "self_tts", False)),\n        "mention_context": args.mention_context,\n',
        "marker self_tts",
    )
    c = replace_once(
        c,
        '    validate_truth_event(row)\n    return row\n',
        '    time_bucket = getattr(args, "time_bucket", None)\n    if time_bucket is not None:\n        row["time_bucket"] = time_bucket\n    validate_truth_event(row)\n    return row\n',
        "marker time bucket",
    )
    c = replace_once(
        c,
        '    mark.add_argument("--voice-level")\n    mark.add_argument("--mention-context", action="store_true")\n',
        '    mark.add_argument("--voice-level")\n    mark.add_argument("--self-tts", action="store_true")\n    mark.add_argument("--time-bucket", choices=["day", "night"])\n    mark.add_argument("--mention-context", action="store_true")\n',
        "marker parser",
    )
    path.write_text(c, encoding="utf-8")


def patch_tests() -> None:
    path = WAKE / "test_v4_eval.py"
    t = path.read_text(encoding="utf-8")
    t = replace_once(
        t,
        'import unittest\n\nfrom v4_eval import Detection, Truth, evaluate, parse_thresholds\n',
        'import json\nimport tempfile\nimport unittest\nfrom pathlib import Path\n\nfrom v4_eval import Detection, Truth, evaluate, load_truth, parse_thresholds, threshold_sweep\n',
        "eval test imports",
    )
    anchor = '    def test_threshold_parse_is_sorted_unique(self):\n        self.assertEqual(parse_thresholds("0.5,0.1,0.5"), [0.1, 0.5])\n'
    insert = '''    def test_benchmark_metadata_fallbacks_and_extended_breakdowns(self):
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
            p.write_text(json.dumps(row, ensure_ascii=False) + "\\n", encoding="utf-8")
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
'''
    t = replace_once(t, anchor, insert, "eval test cases")
    path.write_text(t, encoding="utf-8")

    path = WAKE / "test_v4_benchmark_contract.py"
    q = path.read_text(encoding="utf-8")
    q = replace_once(
        q,
        '            voice_level="normal",\n            mention_context=False,\n            notes=None,\n',
        '            voice_level="normal",\n            self_tts=True,\n            time_bucket="night",\n            mention_context=False,\n            notes=None,\n',
        "contract test marker args",
    )
    q = replace_once(
        q,
        '        self.assertTrue(row["intentional_invocation"])\n        validate_truth_event(row)\n',
        '        self.assertTrue(row["intentional_invocation"])\n        self.assertTrue(row["self_tts"])\n        self.assertEqual(row["time_bucket"], "night")\n        validate_truth_event(row)\n        with self.assertRaisesRegex(ValueError, "self_tts must be boolean"):\n            validate_truth_event(dict(row, self_tts="yes"))\n        with self.assertRaisesRegex(ValueError, "time_bucket must be day or night"):\n            validate_truth_event(dict(row, time_bucket="dusk"))\n',
        "contract test validation",
    )
    path.write_text(q, encoding="utf-8")


def close_checklist(code_sha: str, run_id: str) -> None:
    path = ROOT / "AIHUB_MASTER_EXECUTION_CHECKLIST.md"
    s = path.read_text(encoding="utf-8")
    pairs = [
        (
            '- [ ] **G2.6 Threshold sweep report exists** — P0 / AI-ENG  \n  DoD: threshold vs recall/FRR/FPR-hour is automatically generated.\n',
            f'- [x] **G2.6 Threshold sweep report exists** — P0 / AI-ENG\n  DoD: threshold vs recall/FRR/FPR-hour is automatically generated.\n  Evidence: `v4_eval.py` emits deterministic threshold sweeps with recall, miss/FRR, FPPH and false-alarms/day; CLI report smoke and unit tests passed in run `{run_id}` after commit `{code_sha}`.\n',
        ),
        (
            '- [ ] **G2.7 Condition breakdown exists** — P1 / AI-ENG  \n  DoD: metrics by phrase, speaker, distance, direction, TV/noise, self-TTS, day/night are reported.\n',
            f'- [x] **G2.7 Condition breakdown exists** — P1 / AI-ENG\n  DoD: metrics by phrase, speaker, distance, direction, TV/noise, self-TTS, day/night are reported.\n  Evidence: commit `{code_sha}` adds benchmark-contract metadata and evaluator groups for phrase, speaker, distance bucket, direction, background/TV-noise, voice level, self-TTS and day/night, including `speaker_id`/`room_id` compatibility; tests passed in run `{run_id}`.\n',
        ),
        (
            '- [ ] **G2.9 Statistical confidence is reported** — P1 / AI-ENG  \n  DoD: negative listening hours and confidence bounds accompany false-trigger rates; zero observed events is never presented as zero true rate.\n',
            f'- [x] **G2.9 Statistical confidence is reported** — P1 / AI-ENG\n  DoD: negative listening hours and confidence bounds accompany false-trigger rates; zero observed events is never presented as zero true rate.\n  Evidence: `v4_eval.py` reports negative exposure hours, Wilson recall CI and Poisson false-positive rate CI; the zero-FP unit test verifies a non-zero 95% upper rate bound, and all evaluator tests passed in run `{run_id}`.\n',
        ),
    ]
    for old, new in pairs:
        s = replace_once(s, old, new, old.splitlines()[0])
    path.write_text(s, encoding="utf-8")


def main() -> None:
    mode = os.environ.get("PATCH_MODE", "code")
    if mode == "code":
        patch_eval()
        patch_schema_contract()
        patch_tests()
    elif mode == "checklist":
        close_checklist(os.environ["CODE_SHA"], os.environ["GITHUB_RUN_ID"])
    else:
        raise SystemExit(f"unknown PATCH_MODE={mode}")


if __name__ == "__main__":
    main()
