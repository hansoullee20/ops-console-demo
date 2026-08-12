#!/usr/bin/env python3
"""Generate a fast experimental Okja wake-word dataset.

This intentionally bypasses LiveKit WakeWord's TTS generation stage.  It writes
LiveKit-compatible clip_XXXXXX.wav files directly into the six split folders,
then the normal LiveKit augment/train/export/eval stages can consume them.

MeloTTS Korean has one KR speaker, so this is a v2 *experimental* dataset, not
our final production corpus.  We add controlled pitch/rate/gain variation and
use MeloTTS English's five accents for "Hey Okja".  A later production model
still needs real/multi-speaker Korean positives.
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

POSITIVE_KR = ["옥자", "옥자야"]
POSITIVE_EN = ["Hey Okja"]

# Hard negatives deliberately do NOT contain the exact target phrase "옥자".
# We want "옥자 + more speech" to remain capable of waking the device.
NEGATIVE_KR = [
    "옥상", "옥수수", "독자", "박자", "학자", "저자", "기자", "숫자",
    "액자", "왕자", "상자", "환자", "여자", "부자", "모자", "오자",
    "가자", "앉자", "자자", "옥희", "옥순", "옥경", "옥분", "옥진",
]
NEGATIVE_EN = [
    "Hey", "Okay", "OK Google", "Hey Google", "Okie", "Oka", "Hey Oscar",
    "Hey Olga", "Hey Alexa", "Hey Siri",
]

KR_SPEEDS = [0.82, 0.90, 0.97, 1.03, 1.10, 1.18]
EN_SPEEDS = [0.88, 1.00, 1.12]


def _resample(y: np.ndarray, orig_sr: int, target_sr: int = SAMPLE_RATE) -> np.ndarray:
    if orig_sr == target_sr:
        return y.astype(np.float32)
    import librosa

    return librosa.resample(y.astype(np.float32), orig_sr=orig_sr, target_sr=target_sr).astype(
        np.float32
    )


def _load_mono(path: Path) -> np.ndarray:
    y, sr = sf.read(str(path), dtype="float32")
    if y.ndim > 1:
        y = y[:, 0]
    return _resample(y, sr)


def _perturb(y: np.ndarray, rng: random.Random) -> np.ndarray:
    """Create a deterministic acoustic variant while keeping the phrase intelligible."""
    import librosa

    out = y.astype(np.float32, copy=True)

    # Pitch/formant-like diversity.  This is not a substitute for real speakers,
    # but is useful for a fast classifier iteration.
    semitones = rng.uniform(-3.5, 3.5)
    if abs(semitones) > 0.15:
        out = librosa.effects.pitch_shift(out, sr=SAMPLE_RATE, n_steps=semitones).astype(np.float32)

    # Small independent speaking-rate perturbation.
    rate = rng.uniform(0.92, 1.08)
    if abs(rate - 1.0) > 0.01:
        out = librosa.effects.time_stretch(out, rate=rate).astype(np.float32)

    # Level variation and a little random edge silence.  LiveKit performs the
    # final 2 s alignment during augmentation.
    gain_db = rng.uniform(-7.0, 3.0)
    out *= 10.0 ** (gain_db / 20.0)
    lead = np.zeros(rng.randint(0, int(0.10 * SAMPLE_RATE)), dtype=np.float32)
    trail = np.zeros(rng.randint(0, int(0.08 * SAMPLE_RATE)), dtype=np.float32)
    out = np.concatenate([lead, out, trail])

    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
        out *= 0.98 / peak
    return out.astype(np.float32)


def _synth_bases(tmp: Path) -> tuple[list[np.ndarray], list[np.ndarray]]:
    from melo.api import TTS

    pos: list[np.ndarray] = []
    neg: list[np.ndarray] = []

    print("Loading MeloTTS KR model...", flush=True)
    kr = TTS(language="KR", device="cpu")
    kr_id = kr.hps.data.spk2id["KR"]

    def synth_kr(text: str, speed: float, tag: str) -> np.ndarray:
        p = tmp / f"kr_{tag}_{speed:.2f}.wav"
        kr.tts_to_file(text, kr_id, str(p), speed=speed)
        return _load_mono(p)

    for i, phrase in enumerate(POSITIVE_KR):
        for speed in KR_SPEEDS:
            pos.append(synth_kr(phrase, speed, f"pos_{i}"))
    for i, phrase in enumerate(NEGATIVE_KR):
        # Two base rates per hard negative; augmentation supplies the rest.
        for speed in (0.92, 1.08):
            neg.append(synth_kr(phrase, speed, f"neg_{i}"))

    del kr
    gc.collect()

    print("Loading MeloTTS EN model for Hey Okja + English hard negatives...", flush=True)
    en = TTS(language="EN", device="cpu")
    speaker_ids = en.hps.data.spk2id
    speakers = [k for k in ("EN-US", "EN-BR", "EN_INDIA", "EN-AU", "EN-Default") if k in speaker_ids]

    def synth_en(text: str, speaker: str, speed: float, tag: str) -> np.ndarray:
        p = tmp / f"en_{tag}_{speaker}_{speed:.2f}.wav"
        en.tts_to_file(text, speaker_ids[speaker], str(p), speed=speed)
        return _load_mono(p)

    for phrase_i, phrase in enumerate(POSITIVE_EN):
        for speaker in speakers:
            for speed in EN_SPEEDS:
                pos.append(synth_en(phrase, speaker, speed, f"pos_{phrase_i}"))
    for phrase_i, phrase in enumerate(NEGATIVE_EN):
        for speaker in speakers:
            neg.append(synth_en(phrase, speaker, 1.0, f"neg_{phrase_i}"))

    del en
    gc.collect()
    print(f"Base clips: positive={len(pos)} negative={len(neg)}", flush=True)
    return pos, neg


def _write_variants(
    bases: list[np.ndarray], out_dir: Path, count: int, seed: int
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    for i in range(count):
        base = bases[rng.randrange(len(bases))]
        y = _perturb(base, rng)
        sf.write(str(out_dir / f"clip_{i:06d}.wav"), y, SAMPLE_RATE, subtype="PCM_16")
    print(f"Wrote {count} clips -> {out_dir}", flush=True)


def generate_speech(args: argparse.Namespace) -> None:
    model_dir = Path(args.output_root) / args.model_name
    with tempfile.TemporaryDirectory(prefix="okja_melo_") as td:
        pos_bases, neg_bases = _synth_bases(Path(td))

    _write_variants(pos_bases, model_dir / "positive_train", args.positive_train, 1101)
    _write_variants(pos_bases, model_dir / "positive_test", args.positive_test, 2101)
    _write_variants(neg_bases, model_dir / "negative_train", args.negative_train, 3101)
    _write_variants(neg_bases, model_dir / "negative_test", args.negative_test, 4101)


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
        reps = math.ceil(target / len(y))
        y = np.tile(y, reps)
    start = rng.randint(0, max(0, len(y) - target))
    out = y[start : start + target].astype(np.float32)
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.98:
        out *= 0.98 / peak
    return out


def _write_background_split(
    sources: list[Path], out_dir: Path, count: int, seconds: float, seed: int
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    for i in range(count):
        source = sources[rng.randrange(len(sources))]
        y = _background_clip(source, seconds, rng)
        sf.write(str(out_dir / f"clip_{i:06d}.wav"), y, SAMPLE_RATE, subtype="PCM_16")
    print(f"Wrote {count} background clips -> {out_dir}", flush=True)


def generate_background(args: argparse.Namespace) -> None:
    sources = _collect_backgrounds(Path(args.background_root))
    model_dir = Path(args.output_root) / args.model_name
    print(f"Found {len(sources)} raw background WAVs", flush=True)
    _write_background_split(sources, model_dir / "background_train", args.train, args.seconds, 5101)
    _write_background_split(sources, model_dir / "background_test", args.test, args.seconds, 6101)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)

    speech = sub.add_parser("speech")
    speech.add_argument("--output-root", default="wakeword_v2_output")
    speech.add_argument("--model-name", default="okja_v2_melotts")
    speech.add_argument("--positive-train", type=int, default=256)
    speech.add_argument("--positive-test", type=int, default=64)
    speech.add_argument("--negative-train", type=int, default=512)
    speech.add_argument("--negative-test", type=int, default=128)
    speech.set_defaults(func=generate_speech)

    bg = sub.add_parser("background")
    bg.add_argument("--background-root", required=True)
    bg.add_argument("--output-root", default="wakeword_v2_output")
    bg.add_argument("--model-name", default="okja_v2_melotts")
    bg.add_argument("--train", type=int, default=128)
    bg.add_argument("--test", type=int, default=32)
    bg.add_argument("--seconds", type=float, default=2.0)
    bg.set_defaults(func=generate_background)
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
