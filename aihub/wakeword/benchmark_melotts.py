#!/usr/bin/env python3
import csv
import os
import time
from pathlib import Path

import soundfile as sf
from melo.api import TTS

OUT = Path(os.environ.get("MELOTTS_OUT", "melotts_benchmark"))
OUT.mkdir(parents=True, exist_ok=True)

# Wake positives plus phonetically/semantically nearby negatives.
CASES = [
    ("pos_okja_090", "옥자", 0.90),
    ("pos_okja_100", "옥자", 1.00),
    ("pos_okja_110", "옥자", 1.10),
    ("pos_okjaya_090", "옥자야", 0.90),
    ("pos_okjaya_100", "옥자야", 1.00),
    ("pos_okjaya_110", "옥자야", 1.10),
    ("neg_okssu", "옥수수", 1.00),
    ("neg_okssang", "옥상", 1.00),
    ("neg_dokja", "독자", 1.00),
    ("neg_bakja", "박자", 1.00),
    ("neg_oja", "오자", 1.00),
    ("neg_yeoja", "여자", 1.00),
]

print("Loading MeloTTS Korean model on CPU...", flush=True)
t0 = time.perf_counter()
model = TTS(language="KR", device="cpu")
load_s = time.perf_counter() - t0
speaker_ids = model.hps.data.spk2id
speaker_id = speaker_ids["KR"]
print(f"MODEL_LOAD_SECONDS={load_s:.3f}", flush=True)
print(f"SPEAKER_IDS={speaker_ids}", flush=True)

rows = []
total_gen = 0.0
total_audio = 0.0

for name, text, speed in CASES:
    wav = OUT / f"{name}.wav"
    t1 = time.perf_counter()
    model.tts_to_file(text, speaker_id, str(wav), speed=speed)
    gen_s = time.perf_counter() - t1
    info = sf.info(str(wav))
    audio_s = info.frames / float(info.samplerate)
    rtf = gen_s / audio_s if audio_s else float("inf")
    total_gen += gen_s
    total_audio += audio_s
    row = {
        "name": name,
        "text": text,
        "speed": speed,
        "generation_seconds": round(gen_s, 4),
        "audio_seconds": round(audio_s, 4),
        "rtf": round(rtf, 4),
        "sample_rate": info.samplerate,
        "frames": info.frames,
        "bytes": wav.stat().st_size,
    }
    rows.append(row)
    print(
        f"CASE {name}: gen={gen_s:.3f}s audio={audio_s:.3f}s "
        f"RTF={rtf:.3f} sr={info.samplerate}",
        flush=True,
    )

with (OUT / "results.csv").open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

avg_rtf = total_gen / total_audio if total_audio else float("inf")
summary = (
    f"model_load_seconds={load_s:.3f}\n"
    f"samples={len(rows)}\n"
    f"total_generation_seconds={total_gen:.3f}\n"
    f"total_audio_seconds={total_audio:.3f}\n"
    f"aggregate_rtf={avg_rtf:.4f}\n"
)
(OUT / "summary.txt").write_text(summary, encoding="utf-8")
print("--- SUMMARY ---")
print(summary, end="")
