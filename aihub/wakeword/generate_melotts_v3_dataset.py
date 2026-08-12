#!/usr/bin/env python3
"""Generate the Okja v3 Korean-probe dataset.

v2 proved the LiveKit training/export pipeline works but produced a classifier
with poor separation (13.3% recall / 2.66 FPPH at threshold 0.5).  This v3
experiment deliberately answers a narrower question before we spend time on a
production corpus:

    Can the current MeloTTS + LiveKit pipeline learn the core Korean wake word
    "옥자" when English/multi-phrase mixing is removed and ordinary Korean
    speech is represented heavily in the negative class?

The current MeloTTS Korean checkpoint is still a single-speaker source.  Pitch,
rate and level perturbations do NOT turn it into a true multi-speaker corpus.
A successful v3 therefore justifies a later real/multi-speaker corpus; it does
not qualify the model for Android production use by itself.
"""

from __future__ import annotations

import argparse
import gc
import math
import random
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

SAMPLE_RATE = 16_000
TARGET = "옥자"

# Phonetically close rejection set.  The exact target string is intentionally
# absent: "옥자 + command" should eventually remain a valid wake pattern.
HARD_NEGATIVES = [
    "옥상", "옥수수", "독자", "박자", "학자", "저자", "기자", "숫자",
    "액자", "왕자", "상자", "환자", "여자", "부자", "모자", "오자",
    "가자", "앉자", "자자", "옥희", "옥순", "옥경", "옥분", "옥진",
    "혹자", "목자", "족자", "적자", "흑자", "타자", "투자", "전자",
]

# v2 had hard negatives but almost no ordinary speech in the training class
# because ACAV was skipped.  These sentences cheaply add speech diversity to
# the *training* negatives.  They are intentionally mundane home/TV-like Korean
# and do not contain the target string.
GENERAL_NEGATIVES = [
    "오늘 날씨가 정말 좋네", "지금 몇 시야", "불 좀 켜 줘", "불 좀 꺼 줘",
    "텔레비전 소리 줄여 줘", "텔레비전 소리 올려 줘", "문이 열려 있어",
    "창문 좀 닫아 줘", "에어컨 켜 줘", "에어컨 꺼 줘", "선풍기 켜 줘",
    "음악 틀어 줘", "음악 멈춰 줘", "다음 노래 틀어 줘", "전화가 왔어",
    "핸드폰 어디 있지", "내일 일정 알려 줘", "오늘 일정 알려 줘",
    "약 먹을 시간이야", "물 한 잔 마셔", "밥 먹었어", "뭐 먹을까",
    "잠깐만 기다려", "조금 이따 하자", "나중에 다시 말해 줘",
    "잘 들리지 않아", "다시 한번 말해 봐", "무슨 말인지 모르겠어",
    "이거 어떻게 하는 거야", "거기 누구 있어", "누가 왔어",
    "현관문 확인해 줘", "택배가 도착했어", "오늘은 집에 있을 거야",
    "내일 아침 일찍 일어나야 해", "알람 맞춰 줘", "알람 꺼 줘",
    "타이머 시작해 줘", "십 분 뒤에 알려 줘", "뉴스 보여 줘",
    "뉴스 들려 줘", "사진 보여 줘", "화면 좀 밝게 해 줘",
    "화면 좀 어둡게 해 줘", "볼륨을 낮춰 줘", "볼륨을 높여 줘",
    "방이 조금 춥네", "방이 너무 더워", "습도가 높은 것 같아",
    "공기가 좀 답답해", "환기해야겠다", "청소기 돌려 줘",
    "로봇 청소기 멈춰 줘", "침실 불 켜 줘", "거실 불 꺼 줘",
    "주방 불 켜 줘", "커튼 열어 줘", "커튼 닫아 줘", "문 잠가 줘",
    "문 열어 줘", "오늘 비 온대", "우산 챙겨", "밖에 많이 추워",
    "밖에 많이 더워", "조심해서 다녀와", "다녀왔어", "잘 자",
    "좋은 아침이야", "안녕하세요", "고마워", "괜찮아", "됐어",
    "그래 그렇게 해", "아니 그건 하지 마", "맞아", "아니야",
    "잠깐 생각해 볼게", "이따 전화할게", "지금 통화 가능해",
    "메시지 보내 줘", "문자 읽어 줘", "사진 찍어 줘", "영상 틀어 줘",
    "유튜브 켜 줘", "검색해 줘", "길 좀 찾아 줘", "집으로 가자",
    "병원에 가야 해", "약국 어디야", "마트에 다녀올게", "뭘 사야 하지",
    "냉장고에 뭐가 있어", "세탁기 돌려야 해", "빨래 다 됐나",
    "오늘 쓰레기 버리는 날이야", "가스 잠갔어", "전기 껐어",
    "열쇠 어디 뒀지", "안경 어디 있지", "리모컨 어디 있지",
]

# Keep synthesis bases disjoint by speed between train and validation.  This is
# not speaker independence, but it prevents byte-near-identical bases from
# appearing on both sides before augmentation.
POS_TRAIN_SPEEDS = [0.78, 0.84, 0.90, 0.96, 1.02, 1.08, 1.14, 1.20]
POS_TEST_SPEEDS = [0.81, 0.87, 0.93, 0.99, 1.05, 1.11, 1.17]
NEG_TRAIN_SPEEDS = [0.90, 1.06]
NEG_TEST_SPEEDS = [0.96]


def _resample(y: np.ndarray, orig_sr: int, target_sr: int = SAMPLE_RATE) -> np.ndarray:
    if orig_sr == target_sr:
        return y.astype(np.float32)
    import librosa

    return librosa.resample(
        y.astype(np.float32), orig_sr=orig_sr, target_sr=target_sr
    ).astype(np.float32)


def _load_mono(path: Path) -> np.ndarray:
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y[:, 0]
    return _resample(y, sr)


def _perturb(y: np.ndarray, rng: random.Random) -> np.ndarray:
    import librosa

    out = y.astype(np.float32, copy=True)
    semitones = rng.uniform(-4.0, 4.0)
    if abs(semitones) > 0.15:
        out = librosa.effects.pitch_shift(
            out, sr=SAMPLE_RATE, n_steps=semitones
        ).astype(np.float32)

    rate = rng.uniform(0.90, 1.10)
    if abs(rate - 1.0) > 0.01:
        out = librosa.effects.time_stretch(out, rate=rate).astype(np.float32)

    out *= 10.0 ** (rng.uniform(-9.0, 3.0) / 20.0)
    lead = np.zeros(rng.randint(0, int(0.14 * SAMPLE_RATE)), dtype=np.float32)
    trail = np.zeros(rng.randint(0, int(0.10 * SAMPLE_RATE)), dtype=np.float32)
    out = np.concatenate([lead, out, trail])

    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
        out *= 0.98 / peak
    return out.astype(np.float32)


def _synth_split_bases(tmp: Path) -> dict[str, list[np.ndarray]]:
    from melo.api import TTS

    print("Loading MeloTTS KR model...", flush=True)
    tts = TTS(language="KR", device="cpu")
    speaker_id = tts.hps.data.spk2id["KR"]

    def synth(text: str, speed: float, tag: str) -> np.ndarray:
        path = tmp / f"{tag}_{speed:.2f}.wav"
        tts.tts_to_file(text, speaker_id, str(path), speed=speed)
        return _load_mono(path)

    pos_train = [synth(TARGET, s, "pos_train") for s in POS_TRAIN_SPEEDS]
    pos_test = [synth(TARGET, s, "pos_test") for s in POS_TEST_SPEEDS]

    hard_train: list[np.ndarray] = []
    hard_test: list[np.ndarray] = []
    general_train: list[np.ndarray] = []
    general_test: list[np.ndarray] = []

    # Phrase split: every fifth phrase is validation-only.  Training and test do
    # not share negative text, which makes the hard-negative check less circular.
    for i, text in enumerate(HARD_NEGATIVES):
        if i % 5 == 0:
            hard_test.extend(synth(text, s, f"hard_test_{i}") for s in NEG_TEST_SPEEDS)
        else:
            hard_train.extend(synth(text, s, f"hard_train_{i}") for s in NEG_TRAIN_SPEEDS)

    for i, text in enumerate(GENERAL_NEGATIVES):
        if i % 5 == 0:
            general_test.extend(synth(text, s, f"general_test_{i}") for s in NEG_TEST_SPEEDS)
        else:
            general_train.extend(synth(text, s, f"general_train_{i}") for s in NEG_TRAIN_SPEEDS)

    del tts
    gc.collect()

    pools = {
        "positive_train": pos_train,
        "positive_test": pos_test,
        "hard_train": hard_train,
        "hard_test": hard_test,
        "general_train": general_train,
        "general_test": general_test,
    }
    print(
        "Base clips: " + " ".join(f"{k}={len(v)}" for k, v in pools.items()),
        flush=True,
    )
    return pools


def _write_variants(
    bases: list[np.ndarray], out_dir: Path, count: int, seed: int, start_index: int = 0
) -> None:
    if not bases:
        raise ValueError(f"No bases for {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    for offset in range(count):
        base = bases[rng.randrange(len(bases))]
        y = _perturb(base, rng)
        i = start_index + offset
        sf.write(str(out_dir / f"clip_{i:06d}.wav"), y, SAMPLE_RATE, subtype="PCM_16")


def generate_speech(args: argparse.Namespace) -> None:
    model_dir = Path(args.output_root) / args.model_name
    with tempfile.TemporaryDirectory(prefix="okja_melo_v3_") as td:
        pools = _synth_split_bases(Path(td))

    _write_variants(pools["positive_train"], model_dir / "positive_train", args.positive_train, 7101)
    _write_variants(pools["positive_test"], model_dir / "positive_test", args.positive_test, 7201)

    # Force a 50/50 hard-vs-ordinary-speech negative mixture.  In v2 the only
    # sizeable speech negative source was the hand-written hard-negative list.
    train_hard = args.negative_train // 2
    train_general = args.negative_train - train_hard
    test_hard = args.negative_test // 2
    test_general = args.negative_test - test_hard

    neg_train = model_dir / "negative_train"
    neg_test = model_dir / "negative_test"
    _write_variants(pools["hard_train"], neg_train, train_hard, 7301, 0)
    _write_variants(pools["general_train"], neg_train, train_general, 7401, train_hard)
    _write_variants(pools["hard_test"], neg_test, test_hard, 7501, 0)
    _write_variants(pools["general_test"], neg_test, test_general, 7601, test_hard)

    print(
        f"Wrote speech dataset: positive_train={args.positive_train} "
        f"positive_test={args.positive_test} negative_train={args.negative_train} "
        f"negative_test={args.negative_test}",
        flush=True,
    )


def _collect_backgrounds(root: Path) -> list[Path]:
    files = sorted(root.glob("**/*.wav"))
    if not files:
        raise FileNotFoundError(f"No background WAV files under {root}")
    return files


def _background_clip(path: Path, seconds: float, rng: random.Random) -> np.ndarray:
    y = _load_mono(path)
    target = int(seconds * SAMPLE_RATE)
    if len(y) == 0:
        return np.zeros(target, dtype=np.float32)
    if len(y) < target:
        y = np.tile(y, math.ceil(target / len(y)))
    start = rng.randint(0, max(0, len(y) - target))
    out = y[start : start + target].astype(np.float32)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
        out *= 0.98 / peak
    return out


def generate_background(args: argparse.Namespace) -> None:
    sources = _collect_backgrounds(Path(args.background_root))
    model_dir = Path(args.output_root) / args.model_name
    print(f"Found {len(sources)} raw background WAVs", flush=True)
    rng = random.Random(7701)
    for split, count in (("background_train", args.train), ("background_test", args.test)):
        out_dir = model_dir / split
        out_dir.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            y = _background_clip(sources[rng.randrange(len(sources))], args.seconds, rng)
            sf.write(str(out_dir / f"clip_{i:06d}.wav"), y, SAMPLE_RATE, subtype="PCM_16")
        print(f"Wrote {count} clips -> {out_dir}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)

    speech = sub.add_parser("speech")
    speech.add_argument("--output-root", default="wakeword_v3_output")
    speech.add_argument("--model-name", default="okja_v3_korean_probe")
    speech.add_argument("--positive-train", type=int, default=1024)
    speech.add_argument("--positive-test", type=int, default=256)
    speech.add_argument("--negative-train", type=int, default=4096)
    speech.add_argument("--negative-test", type=int, default=512)
    speech.set_defaults(func=generate_speech)

    background = sub.add_parser("background")
    background.add_argument("--background-root", required=True)
    background.add_argument("--output-root", default="wakeword_v3_output")
    background.add_argument("--model-name", default="okja_v3_korean_probe")
    background.add_argument("--train", type=int, default=256)
    background.add_argument("--test", type=int, default=64)
    background.add_argument("--seconds", type=float, default=2.0)
    background.set_defaults(func=generate_background)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
