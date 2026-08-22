from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

LABELS = ("TV_ON", "TV_OFF", "AC_ON", "AC_OFF", "OTHER")
EXPECTED_SCHEMA = "okja.physical-command-corpus.v2"
SAMPLE_RATE_HZ = 16_000
INPUT_SAMPLES = 48_000


@dataclass(frozen=True)
class CorpusRow:
    index: int
    label: str
    prompt: str
    speaker_id: str
    session_id: str
    condition: str
    pcm_path: Path
    sample_count: int
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_corpus(root: Path, require_exact_samples: bool = True) -> list[CorpusRow]:
    root = root.resolve()
    manifest = root / "manifest.jsonl"
    if not manifest.is_file():
        raise ValueError(f"manifest not found: {manifest}")

    rows: list[CorpusRow] = []
    seen_hashes: dict[str, int] = {}
    for index, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"manifest line {index}: invalid JSON: {exc}") from exc

        required = {
            "schema",
            "label",
            "prompt",
            "speaker_id",
            "session_id",
            "condition",
            "pcm_file",
            "sample_rate_hz",
            "channels",
            "encoding",
            "sample_count",
            "sha256",
            "capture_owner",
            "pcm_continuity_verified",
        }
        missing = sorted(required - record.keys())
        if missing:
            raise ValueError(f"manifest line {index}: missing fields {missing}")
        if record["schema"] != EXPECTED_SCHEMA:
            raise ValueError(
                f"manifest line {index}: expected schema {EXPECTED_SCHEMA}, got {record['schema']}"
            )
        label = str(record["label"])
        if label not in LABELS:
            raise ValueError(f"manifest line {index}: unsupported label {label}")
        if int(record["sample_rate_hz"]) != SAMPLE_RATE_HZ:
            raise ValueError(f"manifest line {index}: sample rate must be {SAMPLE_RATE_HZ}")
        if int(record["channels"]) != 1:
            raise ValueError(f"manifest line {index}: channels must be 1")
        if str(record["encoding"]) != "pcm_s16le":
            raise ValueError(f"manifest line {index}: encoding must be pcm_s16le")
        if str(record["capture_owner"]) != "AudioEngine":
            raise ValueError(f"manifest line {index}: capture_owner must be AudioEngine")
        if record["pcm_continuity_verified"] is not True:
            raise ValueError(f"manifest line {index}: unverified PCM continuity")

        speaker_id = str(record["speaker_id"]).strip()
        session_id = str(record["session_id"]).strip()
        condition = str(record["condition"]).strip()
        prompt = str(record["prompt"]).strip()
        if not speaker_id or not session_id or not condition or not prompt:
            raise ValueError(f"manifest line {index}: provenance/prompt fields cannot be blank")

        relative = Path(str(record["pcm_file"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"manifest line {index}: unsafe pcm_file path {relative}")
        pcm_path = (root / relative).resolve()
        if pcm_path.parent != root:
            raise ValueError(f"manifest line {index}: pcm_file must be directly under corpus root")
        if not pcm_path.is_file():
            raise ValueError(f"manifest line {index}: missing PCM file {pcm_path.name}")
        if pcm_path.stat().st_size % 2:
            raise ValueError(f"manifest line {index}: PCM byte count is not int16-aligned")

        sample_count = int(record["sample_count"])
        actual_samples = pcm_path.stat().st_size // 2
        if sample_count != actual_samples:
            raise ValueError(
                f"manifest line {index}: sample_count={sample_count}, file={actual_samples}"
            )
        if require_exact_samples and sample_count != INPUT_SAMPLES:
            raise ValueError(
                f"manifest line {index}: training requires exactly {INPUT_SAMPLES} samples, "
                f"got {sample_count}"
            )

        expected_hash = str(record["sha256"]).lower()
        actual_hash = _sha256(pcm_path)
        if actual_hash != expected_hash:
            raise ValueError(f"manifest line {index}: SHA-256 mismatch for {pcm_path.name}")
        if actual_hash in seen_hashes:
            raise ValueError(
                f"manifest line {index}: duplicate PCM bytes also used on line "
                f"{seen_hashes[actual_hash]}"
            )
        seen_hashes[actual_hash] = index

        rows.append(
            CorpusRow(
                index=index,
                label=label,
                prompt=prompt,
                speaker_id=speaker_id,
                session_id=session_id,
                condition=condition,
                pcm_path=pcm_path,
                sample_count=sample_count,
                sha256=actual_hash,
            )
        )

    if not rows:
        raise ValueError("corpus is empty")
    return rows


def counts_by(rows: Iterable[CorpusRow], attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, attribute))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def split_by_session(
    rows: list[CorpusRow],
    seed: int,
) -> dict[str, list[CorpusRow]]:
    sessions = sorted({row.session_id for row in rows})
    if len(sessions) < 3:
        raise ValueError(
            "at least 3 distinct capture sessions are required for train/validation/test splitting"
        )

    def rank(session_id: str) -> str:
        return hashlib.sha256(f"{seed}:{session_id}".encode("utf-8")).hexdigest()

    sessions.sort(key=rank)
    n = len(sessions)
    n_test = max(1, round(n * 0.15))
    n_val = max(1, round(n * 0.15))
    if n_test + n_val >= n:
        n_test = 1
        n_val = 1
    test_sessions = set(sessions[:n_test])
    val_sessions = set(sessions[n_test : n_test + n_val])

    split = {"train": [], "validation": [], "test": []}
    for row in rows:
        if row.session_id in test_sessions:
            split["test"].append(row)
        elif row.session_id in val_sessions:
            split["validation"].append(row)
        else:
            split["train"].append(row)

    for name, part in split.items():
        labels = {row.label for row in part}
        missing = sorted(set(LABELS) - labels)
        if missing:
            raise ValueError(
                f"{name} split lacks labels {missing}; collect complete sessions before training"
            )
    return split
