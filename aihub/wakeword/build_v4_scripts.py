#!/usr/bin/env python3
"""Build copyright-clean phase-1 text manifests for Okja v4.

This script does NOT synthesize audio. It creates deterministic, labeled Korean and
English prompts so TTS generation can be audited before expensive training.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
from pathlib import Path

from v4_dataset_tools import normalize_text, stable_bucket

SEED = 20260812

KO_WAKE = ["옥자", "옥자야", "헤이 옥자", "오케이 옥자"]
EN_WAKE = ["Okja", "Hey Okja", "Okay Okja"]

KO_COMMANDS = [
    "지금 몇 시야?", "오늘 날씨 알려줘.", "불 좀 켜줘.", "내 휴대폰 찾아줘.",
    "엄마한테 전화해줘.", "음악 틀어줘.", "내일 일정 알려줘.", "타이머 맞춰줘.",
    "거실 불 꺼줘.", "오늘 비 와?", "뉴스 알려줘.", "소리 조금 줄여줘.",
]
EN_COMMANDS = [
    "what time is it?", "what is the weather today?", "turn on the light.",
    "find my phone.", "call Mom.", "play some music.", "what is on my schedule tomorrow?",
    "set a timer.", "turn off the living room light.", "is it going to rain today?",
]

KO_NEG_A = [
    "오늘", "내일", "아까", "지금", "저녁에", "점심에", "주말에", "집에 오면",
    "텔레비전 보다가", "전화 끝나고", "밥 먹고", "밖에 나가기 전에",
]
KO_NEG_B = [
    "뭐 먹을까?", "택배 어디 뒀어?", "창문 좀 닫아줘.", "비가 오는 것 같아.",
    "냉장고에 넣어 놨어.", "조금 있다가 다시 이야기하자.", "몇 시에 출발할 거야?",
    "그 사람 이름이 뭐였지?", "소리가 너무 큰 것 같아.", "전화가 계속 오네.",
    "커피 한 잔 마실래?", "오늘은 집에서 쉬고 싶어.", "이거 어디에서 샀어?",
    "잠깐만 기다려 봐.", "문이 열려 있는 것 같은데.",
]
EN_NEG_A = [
    "Today", "Tomorrow", "Earlier", "Right now", "After dinner", "This weekend",
    "When I get home", "After the call", "Before we leave", "While the TV is on",
]
EN_NEG_B = [
    "what should we eat?", "where did you put the package?", "please close the window.",
    "I think it is raining.", "I put it in the refrigerator.", "let's talk about it later.",
    "what time are we leaving?", "what was that person's name?", "the TV is too loud.",
    "do you want some coffee?", "I want to stay home today.", "wait a second.",
]

# Manually review/expand these before large-scale synthesis.
KO_HARD_NEG = [
    "옥상에 올라갔어.", "옥수수 좀 사 와.", "독자가 편지를 보냈어.", "목자가 양을 돌봤다.",
    "옥 장판을 새로 깔았어.", "그 글을 읽는 독자들이 많아.",
]
EN_HARD_NEG = [
    "Okay, John, let's go.", "Hey, gotcha.", "Okay, got it.", "Hey, Roger.",
    "The object is over there.", "Okay, Jack, your turn.",
]

KO_MENTION = [
    "어제 옥자라는 영화를 봤어.", "옥자라는 이름을 들어봤어?", "그 사람 이름이 옥자였어.",
    "우리 동네에도 옥자라는 분이 살았어.",
]
EN_MENTION = [
    "I watched Okja last night.", "Have you heard the name Okja?", "Her name was Okja.",
    "We were talking about the movie Okja.",
]

KO_DEVICE_PLAYBACK = [
    "텔레비전에서 옥자야라고 말했어.",
    "영상 속 인물이 옥자를 불렀어.",
    "스피커 광고에서 헤이 옥자라고 들렸어.",
]
EN_DEVICE_PLAYBACK = [
    "The television character said Hey Okja.",
    "The video called out Okja by name.",
    "The speaker advertisement said Okay Okja.",
]

KO_TRUNCATED = ["옥...", "옥자, 아니 잠깐.", "헤이 옥... 됐어."]
EN_TRUNCATED = ["Ok...", "Okja, no, wait.", "Hey Ok... never mind."]

KO_NEAR_MISS = ["옥차 불러 줘.", "목자야 이리 와.", "독자야 질문 있어.", "옥수야 전화해 줘."]
EN_NEAR_MISS = ["Okay Josh, let's go.", "Hey Oscar, come here.", "Okay Jack, call me.", "Hey Roger, your turn."]

REQUIRED_SCENARIOS = {
    "positive_wake",
    "ordinary_negative",
    "hard_phonetic_negative",
    "mention_context",
    "device_playback",
    "truncated_wake",
    "near_miss_wake",
}


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "script_id",
        "language",
        "label",
        "scenario",
        "wake_variant",
        "text",
        "normalized_text",
        "template_id",
        "split_group",
        "split",
        "source_id",
        "source_license",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def stable_script_id(
    language: str,
    label: str,
    scenario: str,
    text: str,
    wake_variant: str,
) -> str:
    key = "\x1f".join(
        (language, label, scenario, normalize_text(text), normalize_text(wake_variant))
    )
    return f"v4s_{language}_{hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]}"


def planned_split(script_id: str) -> str:
    return "train" if stable_bucket(script_id) < 8000 else "validation"


def validate_rows(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    texts: set[tuple[str, str]] = set()
    scenarios: set[str] = set()
    for row in rows:
        script_id = row["script_id"]
        if script_id in ids:
            errors.append(f"duplicate script_id: {script_id}")
        ids.add(script_id)

        text_key = (row["language"], row["normalized_text"])
        if text_key in texts:
            errors.append(f"duplicate normalized text: {text_key[0]}/{text_key[1]}")
        texts.add(text_key)

        scenarios.add(row["scenario"])
        if row["split_group"] != script_id or row["template_id"] != script_id:
            errors.append(f"{script_id}: split/template identity mismatch")
        if row["split"] not in {"train", "validation"}:
            errors.append(f"{script_id}: invalid planned split {row['split']!r}")

    for scenario in sorted(REQUIRED_SCENARIOS - scenarios):
        errors.append(f"missing scenario: {scenario}")
    return errors


def build(repeats: int) -> list[dict]:
    if repeats <= 0:
        raise ValueError("negative_repeats must be positive")
    rng = random.Random(SEED)
    rows: list[dict] = []

    def add(language, label, scenario, text, wake_variant=""):
        script_id = stable_script_id(language, label, scenario, text, wake_variant)
        normalized = normalize_text(text)
        rows.append({
            "id": script_id,
            "script_id": script_id,
            "language": language,
            "label": label,
            "scenario": scenario,
            "wake_variant": wake_variant,
            "text": text,
            "normalized_text": normalized,
            "template_id": script_id,
            "split_group": script_id,
            "split": planned_split(script_id),
            "source_id": "okja_original_scripts",
            "source_license": "project-owned original text",
        })

    for wake in KO_WAKE:
        add("ko", "positive", "positive_wake", wake, wake)
        for cmd in KO_COMMANDS:
            add("ko", "positive", "positive_wake", f"{wake}, {cmd}", wake)
    for wake in EN_WAKE:
        add("en", "positive", "positive_wake", wake, wake)
        for cmd in EN_COMMANDS:
            add("en", "positive", "positive_wake", f"{wake}, {cmd}", wake)

    # This is a text library, not a synthesis request list. Shuffle the unique
    # Cartesian products deterministically and cap them; voice/seed expansion
    # happens later without creating duplicate script identities.
    ko_negatives = [f"{a} {b}" for a in KO_NEG_A for b in KO_NEG_B]
    en_negatives = [f"{a}, {b}" for a in EN_NEG_A for b in EN_NEG_B]
    rng.shuffle(ko_negatives)
    rng.shuffle(en_negatives)
    for text in ko_negatives[:repeats]:
        add("ko", "negative", "ordinary_negative", text)
    for text in en_negatives[:repeats]:
        add("en", "negative", "ordinary_negative", text)

    for text in KO_HARD_NEG:
        add("ko", "hard_negative", "hard_phonetic_negative", text)
    for text in EN_HARD_NEG:
        add("en", "hard_negative", "hard_phonetic_negative", text)
    for text in KO_MENTION:
        add("ko", "mention_context", "mention_context", text, "옥자")
    for text in EN_MENTION:
        add("en", "mention_context", "mention_context", text, "Okja")
    for text in KO_DEVICE_PLAYBACK:
        add("ko", "mention_context", "device_playback", text, "옥자")
    for text in EN_DEVICE_PLAYBACK:
        add("en", "mention_context", "device_playback", text, "Okja")
    for text in KO_TRUNCATED:
        add("ko", "hard_negative", "truncated_wake", text)
    for text in EN_TRUNCATED:
        add("en", "hard_negative", "truncated_wake", text)
    for text in KO_NEAR_MISS:
        add("ko", "hard_negative", "near_miss_wake", text)
    for text in EN_NEAR_MISS:
        add("en", "hard_negative", "near_miss_wake", text)

    errors = validate_rows(rows)
    if errors:
        raise ValueError("invalid script library:\n- " + "\n- ".join(errors))

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="aihub/wakeword/v4_scripts.csv")
    ap.add_argument(
        "--negative-repeats",
        type=int,
        default=2000,
        help="maximum unique ordinary-negative prompts per language",
    )
    args = ap.parse_args()
    rows = build(args.negative_repeats)
    write_rows(Path(args.output), rows)
    counts = {}
    for r in rows:
        key = (r["language"], r["label"])
        counts[key] = counts.get(key, 0) + 1
    print(f"wrote {len(rows)} rows to {args.output}")
    for key in sorted(counts):
        print(key, counts[key])
    scenario_counts = {}
    for row in rows:
        scenario_counts[row["scenario"]] = scenario_counts.get(row["scenario"], 0) + 1
    for scenario in sorted(scenario_counts):
        print("scenario", scenario, scenario_counts[scenario])


if __name__ == "__main__":
    main()
