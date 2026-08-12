#!/usr/bin/env python3
"""Build copyright-clean phase-1 text manifests for Okja v4.

This script does NOT synthesize audio. It creates deterministic, labeled Korean and
English prompts so TTS generation can be audited before expensive training.
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

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


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "language", "label", "wake_variant", "text", "split_group"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build(repeats: int) -> list[dict]:
    rng = random.Random(SEED)
    rows: list[dict] = []
    n = 0

    def add(language, label, text, wake_variant="", split_group=""):
        nonlocal n
        n += 1
        rows.append({
            "id": f"v4_{n:06d}", "language": language, "label": label,
            "wake_variant": wake_variant, "text": text,
            "split_group": split_group or f"script_{n:06d}",
        })

    for wake in KO_WAKE:
        add("ko", "positive", wake, wake, f"ko_wake_{wake}")
        for cmd in KO_COMMANDS:
            add("ko", "positive", f"{wake}, {cmd}", wake, f"ko_{wake}_{cmd}")
    for wake in EN_WAKE:
        add("en", "positive", wake, wake, f"en_wake_{wake}")
        for cmd in EN_COMMANDS:
            add("en", "positive", f"{wake}, {cmd}", wake, f"en_{wake}_{cmd}")

    # Generate ordinary negatives from original phrase components.
    for i in range(repeats):
        add("ko", "negative", f"{rng.choice(KO_NEG_A)} {rng.choice(KO_NEG_B)}", split_group=f"ko_neg_{i:05d}")
        add("en", "negative", f"{rng.choice(EN_NEG_A)}, {rng.choice(EN_NEG_B)}", split_group=f"en_neg_{i:05d}")

    for i, text in enumerate(KO_HARD_NEG):
        add("ko", "hard_negative", text, split_group=f"ko_hard_{i}")
    for i, text in enumerate(EN_HARD_NEG):
        add("en", "hard_negative", text, split_group=f"en_hard_{i}")
    for i, text in enumerate(KO_MENTION):
        add("ko", "mention_context", text, "옥자", f"ko_mention_{i}")
    for i, text in enumerate(EN_MENTION):
        add("en", "mention_context", text, "Okja", f"en_mention_{i}")

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default="aihub/wakeword/v4_scripts.csv")
    ap.add_argument("--negative-repeats", type=int, default=2000)
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


if __name__ == "__main__":
    main()
