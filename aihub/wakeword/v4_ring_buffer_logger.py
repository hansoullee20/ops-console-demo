#!/usr/bin/env python3
"""Privacy-first PCM ring-buffer logger for Okja wakeword diagnostics.

Raw audio remains in memory. Only explicit candidate/manual-miss windows are
persisted, with configurable pre/post-roll and JSONL metadata.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PendingCapture:
    event_id: str
    kind: str
    score: float | None
    threshold: float | None
    accepted: bool | None
    metadata: dict[str, Any]
    pcm: array
    remaining_samples: int
    created_monotonic_ms: int


class PcmRingBufferLogger:
    def __init__(
        self,
        output_dir: Path,
        *,
        sample_rate_hz: int = 16000,
        channels: int = 1,
        pre_seconds: float = 3.0,
        post_seconds: float = 2.0,
    ) -> None:
        if sample_rate_hz <= 0 or channels != 1:
            raise ValueError("current logger supports positive sample rate and mono PCM16 only")
        if pre_seconds <= 0 or post_seconds < 0:
            raise ValueError("invalid pre/post capture duration")
        self.output_dir = Path(output_dir)
        self.sample_rate_hz = sample_rate_hz
        self.channels = channels
        self.pre_samples = int(round(sample_rate_hz * pre_seconds))
        self.post_samples = int(round(sample_rate_hz * post_seconds))
        self._ring: deque[int] = deque(maxlen=self.pre_samples)
        self._pending: list[PendingCapture] = []
        self.events_path = self.output_dir / "wake_diagnostic_events.jsonl"

    @property
    def buffered_samples(self) -> int:
        return len(self._ring)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def push_pcm16(self, samples: list[int] | array) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        vals = array("h", samples)

        if self._pending:
            still_pending: list[PendingCapture] = []
            for cap in self._pending:
                take = min(cap.remaining_samples, len(vals))
                if take > 0:
                    cap.pcm.extend(vals[:take])
                    cap.remaining_samples -= take
                if cap.remaining_samples <= 0:
                    completed.append(self._finalize(cap))
                else:
                    still_pending.append(cap)
            self._pending = still_pending

        self._ring.extend(vals)
        return completed

    def capture_candidate(
        self,
        *,
        score: float,
        threshold: float,
        accepted: bool,
        metadata: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> str:
        return self._start_capture(
            kind="candidate",
            score=float(score),
            threshold=float(threshold),
            accepted=bool(accepted),
            metadata=metadata or {},
            event_id=event_id,
        )

    def capture_manual_miss(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> str:
        return self._start_capture(
            kind="manual_miss",
            score=None,
            threshold=None,
            accepted=None,
            metadata=metadata or {},
            event_id=event_id,
        )

    def flush_pending(self) -> list[dict[str, Any]]:
        """Finalize pending captures early, e.g. when capture session stops."""
        completed = [self._finalize(cap) for cap in self._pending]
        self._pending = []
        return completed

    def _start_capture(
        self,
        *,
        kind: str,
        score: float | None,
        threshold: float | None,
        accepted: bool | None,
        metadata: dict[str, Any],
        event_id: str | None,
    ) -> str:
        eid = event_id or f"diag-{uuid.uuid4()}"
        pre = array("h", self._ring)
        cap = PendingCapture(
            event_id=eid,
            kind=kind,
            score=score,
            threshold=threshold,
            accepted=accepted,
            metadata=dict(metadata),
            pcm=pre,
            remaining_samples=self.post_samples,
            created_monotonic_ms=int(time.monotonic() * 1000),
        )
        if self.post_samples == 0:
            self._finalize(cap)
        else:
            self._pending.append(cap)
        return eid

    def _finalize(self, cap: PendingCapture) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        wav_name = f"{cap.event_id}.wav"
        wav_path = self.output_dir / wav_name
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate_hz)
            wf.writeframes(cap.pcm.tobytes())

        digest = hashlib.sha256(wav_path.read_bytes()).hexdigest()
        row = {
            "schema_version": 1,
            "event_id": cap.event_id,
            "kind": cap.kind,
            "created_monotonic_ms": cap.created_monotonic_ms,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "pre_samples_configured": self.pre_samples,
            "post_samples_configured": self.post_samples,
            "saved_samples": len(cap.pcm),
            "wav_filename": wav_name,
            "audio_sha256": digest,
            "score": cap.score,
            "threshold": cap.threshold,
            "accepted": cap.accepted,
            "metadata": cap.metadata,
        }
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return row


__all__ = ["PcmRingBufferLogger"]
