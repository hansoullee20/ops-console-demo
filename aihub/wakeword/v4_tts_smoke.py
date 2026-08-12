#!/usr/bin/env python3
"""Generate a tiny real-TTS Okja v4 smoke corpus.

This is intentionally tiny. Its purpose is to validate model download/inference,
audio normalization, manifest provenance, and downstream QC before any large
corpus generation.

Supported smoke engines:
- kokoro: English only, Apache-2.0 upstream model
- chatterbox: Korean/English multilingual, MIT upstream model

Do not treat this corpus as training data until pronunciation has been reviewed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from importlib.metadata import version as package_version
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

TARGET_SR = 16000
SMOKE_SEED = 20260812
PRE_SILENCE_MS = 350
POST_SILENCE_MS = 550

# Tuple: language, label, canonical text, wake variant, synthesis input text.
# The synthesis input can differ only to probe TTS phrase-boundary/prosody behavior;
# the canonical text remains the semantic label used by the dataset/evaluator.
KOKORO_ITEMS = [
    ("en", "positive", "Okja", "Okja", "Okja."),
    ("en", "positive", "Hey Okja", "Hey Okja", "Hey Okja."),
    ("en", "negative", "What time are we leaving today?", "", "What time are we leaving today?"),
    ("en", "hard_negative", "Okay, John, let's go.", "", "Okay, John, let's go."),
]

# Human QC on 2026-08-13 found the original short Korean positives unsuitable:
# - bare "옥자" sounded clipped/too abrupt;
# - "옥자야, 지금 몇 시야?" could sound closer to "입자...".
# Keep multiple phrase-boundary probes in the smoke corpus until one is explicitly
# approved by a listener. These are audition candidates, not automatically training-safe.
CHATTERBOX_ITEMS = [
    ("ko", "positive", "옥자", "옥자", "옥자."),
    ("ko", "positive", "옥자", "옥자", "옥자..."),
    ("ko", "positive", "옥자야, 지금 몇 시야?", "옥자야", "옥자야. 지금 몇 시야?"),
    ("ko", "positive", "옥자야, 지금 몇 시야?", "옥자야", "옥자야... 지금 몇 시야?"),
    ("ko", "negative", "오늘 저녁은 뭐 먹을까?", "", "오늘 저녁은 뭐 먹을까?"),
    ("ko", "hard_negative", "옥수수 좀 사 와.", "", "옥수수 좀 사 와."),
]


def mono_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    x = np.squeeze(x)
    if x.ndim > 1:
        x = np.mean(x, axis=0)
    if sr != TARGET_SR:
        from math import gcd
        g = gcd(sr, TARGET_SR)
        x = resample_poly(x, TARGET_SR // g, sr // g).astype(np.float32)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 0.98:
        x = x * (0.98 / peak)
    return x.astype(np.float32)


def add_clip_padding(audio: np.ndarray) -> np.ndarray:
    """Add deterministic context margins so short wake clips are not boundary-clipped."""
    pre = np.zeros(round(TARGET_SR * PRE_SILENCE_MS / 1000), dtype=np.float32)
    post = np.zeros(round(TARGET_SR * POST_SILENCE_MS / 1000), dtype=np.float32)
    return np.concatenate([pre, np.asarray(audio, dtype=np.float32), post])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(path: Path, rows: list[dict]) -> None:
    fields = [
        "clip_id", "audio_path", "audio_sha256", "language", "label", "wake_variant", "text",
        "tts_input_text", "script_id", "source_id", "source_license", "tts_engine", "tts_engine_version",
        "voice_id", "generation_seed", "base_audio_id", "augmentation_id", "holdout_role", "split",
        "pre_silence_ms", "post_silence_ms", "sample_rate_hz", "channels", "duration_ms", "qc_status",
        "pronunciation_status", "created_by",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def add_row(rows: list[dict], outdir: Path, engine: str, engine_version: str,
            license_name: str, voice: str, idx: int, language: str, label: str,
            text: str, wake_variant: str, tts_input_text: str,
            audio: np.ndarray, sr: int) -> None:
    clip_id = f"smoke_{engine}_{idx:02d}"
    rel = f"audio/{clip_id}.wav"
    normalized = mono_16k(audio, sr)
    normalized = add_clip_padding(normalized)
    audio_path = outdir / rel
    sf.write(audio_path, normalized, TARGET_SR, subtype="PCM_16")
    rows.append({
        "clip_id": clip_id,
        "audio_path": rel,
        "audio_sha256": sha256_file(audio_path),
        "language": language,
        "label": label,
        "wake_variant": wake_variant,
        "text": text,
        "tts_input_text": tts_input_text,
        "script_id": f"smoke_script_{engine}_{idx:02d}",
        "source_id": "kokoro_82m" if engine == "kokoro" else "chatterbox_multilingual",
        "source_license": license_name,
        "tts_engine": engine,
        "tts_engine_version": engine_version,
        "voice_id": voice,
        "generation_seed": SMOKE_SEED,
        "base_audio_id": clip_id,
        "augmentation_id": "none",
        "holdout_role": "",
        "split": "",
        "pre_silence_ms": PRE_SILENCE_MS,
        "post_silence_ms": POST_SILENCE_MS,
        "sample_rate_hz": TARGET_SR,
        "channels": 1,
        "duration_ms": int(round(len(normalized) * 1000 / TARGET_SR)),
        "qc_status": "pending",
        "pronunciation_status": "not_reviewed",
        "created_by": "v4_tts_smoke.py",
    })


def generate_kokoro(outdir: Path, rows: list[dict]) -> None:
    from kokoro import KPipeline

    np.random.seed(SMOKE_SEED)
    engine_version = package_version("kokoro")
    voice = "af_heart"
    pipeline = KPipeline(lang_code="a")
    for idx, (language, label, text, wake_variant, tts_input_text) in enumerate(KOKORO_ITEMS, 1):
        chunks = []
        for _gs, _ps, audio in pipeline(tts_input_text, voice=voice):
            chunks.append(np.asarray(audio, dtype=np.float32))
        if not chunks:
            raise RuntimeError(f"Kokoro produced no audio for: {tts_input_text}")
        audio = np.concatenate(chunks)
        add_row(rows, outdir, "kokoro", engine_version, "Apache-2.0", voice, idx,
                language, label, text, wake_variant, tts_input_text, audio, 24000)


def generate_chatterbox(outdir: Path, rows: list[dict]) -> None:
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    np.random.seed(SMOKE_SEED)
    torch.manual_seed(SMOKE_SEED)
    engine_version = package_version("chatterbox-tts")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    voice = "default_unconditioned"
    for idx, (language, label, text, wake_variant, tts_input_text) in enumerate(CHATTERBOX_ITEMS, 1):
        wav = model.generate(tts_input_text, language_id=language)
        audio = wav.detach().cpu().numpy()
        add_row(rows, outdir, "chatterbox", engine_version, "MIT", voice, idx,
                language, label, text, wake_variant, tts_input_text, audio, int(model.sr))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["kokoro", "chatterbox"], required=True)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    outdir = Path(args.output_dir)
    (outdir / "audio").mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    if args.engine == "kokoro":
        generate_kokoro(outdir, rows)
    else:
        generate_chatterbox(outdir, rows)

    manifest = outdir / "manifest_raw.csv"
    write_manifest(manifest, rows)
    print(f"generated {len(rows)} real TTS clips -> {outdir}")
    print(f"manifest -> {manifest}")


if __name__ == "__main__":
    main()
