#!/usr/bin/env python3
"""Generate a tiny real-TTS Okja v4 smoke corpus.

This is intentionally tiny. Its purpose is to validate model download/inference,
audio normalization, manifest provenance, and downstream QC before any large
corpus generation.

Supported smoke engines:
- kokoro: English only, Apache-2.0 upstream model
- chatterbox: Korean/English multilingual V3, MIT upstream model

Do not treat this corpus as training data until pronunciation has been reviewed.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

TARGET_SR = 16000

KOKORO_ITEMS = [
    ("en", "positive", "Okja", "Okja"),
    ("en", "positive", "Hey Okja", "Hey Okja"),
    ("en", "negative", "What time are we leaving today?", ""),
    ("en", "hard_negative", "Okay, John, let's go.", ""),
]

CHATTERBOX_ITEMS = [
    ("ko", "positive", "옥자", "옥자"),
    ("ko", "positive", "옥자야, 지금 몇 시야?", "옥자야"),
    ("ko", "negative", "오늘 저녁은 뭐 먹을까?", ""),
    ("ko", "hard_negative", "옥수수 좀 사 와.", ""),
]


def mono_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    x = np.squeeze(x)
    if x.ndim > 1:
        x = np.mean(x, axis=0)
    if sr != TARGET_SR:
        # Integer-rate resampling for deterministic smoke output.
        from math import gcd
        g = gcd(sr, TARGET_SR)
        x = resample_poly(x, TARGET_SR // g, sr // g).astype(np.float32)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 0.98:
        x = x * (0.98 / peak)
    return x.astype(np.float32)


def write_manifest(path: Path, rows: list[dict]) -> None:
    fields = [
        "clip_id", "audio_path", "language", "label", "wake_variant", "text",
        "script_id", "source_id", "source_license", "tts_engine", "voice_id",
        "base_audio_id", "augmentation_id", "holdout_role", "split",
        "sample_rate_hz", "channels", "duration_ms", "qc_status",
        "pronunciation_status", "created_by",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def add_row(rows: list[dict], outdir: Path, engine: str, license_name: str,
            voice: str, idx: int, language: str, label: str, text: str,
            wake_variant: str, audio: np.ndarray, sr: int) -> None:
    clip_id = f"smoke_{engine}_{idx:02d}"
    rel = f"audio/{clip_id}.wav"
    normalized = mono_16k(audio, sr)
    sf.write(outdir / rel, normalized, TARGET_SR, subtype="PCM_16")
    rows.append({
        "clip_id": clip_id,
        "audio_path": rel,
        "language": language,
        "label": label,
        "wake_variant": wake_variant,
        "text": text,
        "script_id": f"smoke_script_{engine}_{idx:02d}",
        "source_id": "kokoro_82m" if engine == "kokoro" else "chatterbox_multilingual_v3",
        "source_license": license_name,
        "tts_engine": engine,
        "voice_id": voice,
        "base_audio_id": clip_id,
        "augmentation_id": "none",
        "holdout_role": "",
        "split": "",
        "sample_rate_hz": TARGET_SR,
        "channels": 1,
        "duration_ms": int(round(len(normalized) * 1000 / TARGET_SR)),
        "qc_status": "pending",
        "pronunciation_status": "not_reviewed",
        "created_by": "v4_tts_smoke.py",
    })


def generate_kokoro(outdir: Path, rows: list[dict]) -> None:
    from kokoro import KPipeline

    voice = "af_heart"
    pipeline = KPipeline(lang_code="a")
    for idx, (language, label, text, wake_variant) in enumerate(KOKORO_ITEMS, 1):
        chunks = []
        for _gs, _ps, audio in pipeline(text, voice=voice):
            chunks.append(np.asarray(audio, dtype=np.float32))
        if not chunks:
            raise RuntimeError(f"Kokoro produced no audio for: {text}")
        audio = np.concatenate(chunks)
        add_row(rows, outdir, "kokoro", "Apache-2.0", voice, idx,
                language, label, text, wake_variant, audio, 24000)


def generate_chatterbox(outdir: Path, rows: list[dict]) -> None:
    import torch
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxMultilingualTTS.from_pretrained(device=device, t3_model="v3")
    voice = "default_unconditioned"
    for idx, (language, label, text, wake_variant) in enumerate(CHATTERBOX_ITEMS, 1):
        wav = model.generate(text, language_id=language)
        audio = wav.detach().cpu().numpy()
        add_row(rows, outdir, "chatterbox", "MIT", voice, idx,
                language, label, text, wake_variant, audio, int(model.sr))


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
