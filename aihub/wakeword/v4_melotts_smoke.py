#!/usr/bin/env python3
"""Generate a tiny Korean MeloTTS smoke corpus for Okja v4.

This is a candidate second Korean TTS source. It is intentionally isolated from
the stable Kokoro/Chatterbox smoke workflow so MeloTTS dependency issues cannot
break the already-green baseline pipeline.

Source pins:
- MeloTTS code: myshell-ai/MeloTTS commit 209145371cff8fc3bd60d7be902ea69cbdb7965a
- MeloTTS Korean weights: myshell-ai/MeloTTS-Korean revision 0207e5adfc90129a51b6b03d89be6d84360ed323

Human pronunciation/naturalness review is required before any generated clip is
training-safe.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

TARGET_SR = 16000
SMOKE_SEED = 20260813
PRE_SILENCE_MS = 350
POST_SILENCE_MS = 550
MELOTTS_CODE_COMMIT = "209145371cff8fc3bd60d7be902ea69cbdb7965a"
MELOTTS_HF_REPO = "myshell-ai/MeloTTS-Korean"
MELOTTS_MODEL_REVISION = "0207e5adfc90129a51b6b03d89be6d84360ed323"

ITEMS = [
    ("positive", "옥자", "옥자", "옥자."),
    ("positive", "옥자야, 지금 몇 시야?", "옥자야", "옥자야. 지금 몇 시야?"),
    ("negative", "오늘 저녁은 뭐 먹을까?", "", "오늘 저녁은 뭐 먹을까?"),
    ("hard_negative", "옥수수 좀 사 와.", "", "옥수수 좀 사 와."),
]


def mono_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    x = np.squeeze(x)
    if x.ndim > 1:
        x = np.mean(x, axis=1 if x.shape[1] <= 2 else 0)
        x = np.squeeze(x)
    if sr != TARGET_SR:
        from math import gcd
        g = gcd(sr, TARGET_SR)
        x = resample_poly(x, TARGET_SR // g, sr // g).astype(np.float32)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 0.98:
        x = x * (0.98 / peak)
    return x.astype(np.float32)


def add_padding(audio: np.ndarray) -> np.ndarray:
    pre = np.zeros(round(TARGET_SR * PRE_SILENCE_MS / 1000), dtype=np.float32)
    post = np.zeros(round(TARGET_SR * POST_SILENCE_MS / 1000), dtype=np.float32)
    return np.concatenate([pre, audio.astype(np.float32), post])


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
        "tts_code_commit", "model_repo", "model_revision", "model_config_sha256", "model_checkpoint_sha256",
        "voice_id", "generation_seed", "base_audio_id", "augmentation_id", "holdout_role", "split",
        "pre_silence_ms", "post_silence_ms", "sample_rate_hz", "channels", "duration_ms", "qc_status",
        "pronunciation_status", "created_by",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    import torch
    from huggingface_hub import hf_hub_download
    from importlib.metadata import version as package_version
    from melo.api import TTS

    np.random.seed(SMOKE_SEED)
    torch.manual_seed(SMOKE_SEED)

    outdir = Path("out/v4-smoke-melotts")
    audio_dir = outdir / "audio"
    raw_dir = outdir / "raw"
    audio_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Pin the *actual model files* to the declared Hugging Face revision. Passing
    # explicit local paths prevents MeloTTS from silently resolving main/latest.
    config_path = Path(hf_hub_download(
        repo_id=MELOTTS_HF_REPO,
        filename="config.json",
        revision=MELOTTS_MODEL_REVISION,
    ))
    checkpoint_path = Path(hf_hub_download(
        repo_id=MELOTTS_HF_REPO,
        filename="checkpoint.pth",
        revision=MELOTTS_MODEL_REVISION,
    ))
    config_sha256 = sha256_file(config_path)
    checkpoint_sha256 = sha256_file(checkpoint_path)
    print(f"MeloTTS model repo: {MELOTTS_HF_REPO}")
    print(f"MeloTTS model revision: {MELOTTS_MODEL_REVISION}")
    print(f"config sha256: {config_sha256}")
    print(f"checkpoint sha256: {checkpoint_sha256}")

    model = TTS(
        language="KR",
        device="cpu",
        config_path=str(config_path),
        ckpt_path=str(checkpoint_path),
    )
    speaker_ids = model.hps.data.spk2id
    if "KR" not in speaker_ids:
        raise RuntimeError(f"MeloTTS Korean speaker id not found: {speaker_ids}")
    voice_id = "KR"
    speaker_id = speaker_ids[voice_id]
    engine_version = package_version("melotts")

    rows: list[dict] = []
    for idx, (label, text, wake_variant, tts_input_text) in enumerate(ITEMS, 1):
        clip_id = f"smoke_melotts_{idx:02d}"
        raw_path = raw_dir / f"{clip_id}_raw.wav"
        model.tts_to_file(tts_input_text, speaker_id, str(raw_path), speed=1.0)
        audio, sr = sf.read(raw_path, dtype="float32", always_2d=False)
        normalized = add_padding(mono_16k(audio, int(sr)))
        rel = f"audio/{clip_id}.wav"
        out_path = outdir / rel
        sf.write(out_path, normalized, TARGET_SR, subtype="PCM_16")
        rows.append({
            "clip_id": clip_id,
            "audio_path": rel,
            "audio_sha256": sha256_file(out_path),
            "language": "ko",
            "label": label,
            "wake_variant": wake_variant,
            "text": text,
            "tts_input_text": tts_input_text,
            "script_id": f"smoke_script_melotts_{idx:02d}",
            "source_id": "melotts_korean",
            "source_license": "MIT",
            "tts_engine": "melotts",
            "tts_engine_version": engine_version,
            "tts_code_commit": MELOTTS_CODE_COMMIT,
            "model_repo": MELOTTS_HF_REPO,
            "model_revision": MELOTTS_MODEL_REVISION,
            "model_config_sha256": config_sha256,
            "model_checkpoint_sha256": checkpoint_sha256,
            "voice_id": voice_id,
            "generation_seed": SMOKE_SEED,
            "base_audio_id": clip_id,
            "augmentation_id": "none",
            "holdout_role": "engine",
            "split": "",
            "pre_silence_ms": PRE_SILENCE_MS,
            "post_silence_ms": POST_SILENCE_MS,
            "sample_rate_hz": TARGET_SR,
            "channels": 1,
            "duration_ms": int(round(len(normalized) * 1000 / TARGET_SR)),
            "qc_status": "pending",
            "pronunciation_status": "not_reviewed",
            "created_by": "v4_melotts_smoke.py",
        })

    write_manifest(outdir / "manifest_raw.csv", rows)
    print(f"generated {len(rows)} MeloTTS Korean clips -> {outdir}")


if __name__ == "__main__":
    main()
