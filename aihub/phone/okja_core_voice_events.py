#!/usr/bin/env python3
"""Exact payload policy for the live recognizer-owned portion of G3.2."""
from __future__ import annotations

from typing import Any, Mapping

from okja_event_contract import validate_event

LIFECYCLE_TYPES = frozenset({
    "wake.candidate", "wake.detected", "wake.rejected",
    "listening.started", "listening.stopped", "listening.failed",
    "transcript.partial", "transcript.final", "transcript.failed",
})

PAYLOAD_FIELDS = {
    "wake.candidate": frozenset({"language", "candidate_count"}),
    "wake.detected": frozenset({"language", "candidate_count"}),
    "wake.rejected": frozenset({"language", "candidate_count", "reason"}),
    "listening.started": frozenset({"language", "entrypoint"}),
    "listening.stopped": frozenset({"language", "reason"}),
    "listening.failed": frozenset({"language", "error_code"}),
    "transcript.partial": frozenset({"language", "text"}),
    "transcript.final": frozenset({"profile", "language", "text"}),
    "transcript.failed": frozenset({"language", "error_code"}),
}


def validate_core_voice_event(event: Mapping[str, Any]) -> dict[str, Any]:
    value = validate_event(event)
    event_type = value["event_type"]
    if event_type not in LIFECYCLE_TYPES:
        raise ValueError("event is not recognizer-owned core voice lifecycle")
    if value["source"] != "android.voice" or value["retention_class"] != "volatile":
        raise ValueError("recognizer lifecycle must be android.voice and volatile")
    payload = value["payload"]
    if set(payload) != PAYLOAD_FIELDS[event_type]:
        raise ValueError(f"{event_type} payload fields are not exact")
    language = payload.get("language")
    if language not in {"ko-KR", "en-US"}:
        raise ValueError("unsupported recognizer language")
    if event_type.startswith("wake."):
        count = payload["candidate_count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > 5:
            raise ValueError("candidate_count must be integer 0..5")
    if event_type == "wake.rejected" and payload["reason"] not in {"phrase_mismatch", "empty_result"}:
        raise ValueError("wake rejection reason is unsupported")
    if event_type == "listening.started" and payload["entrypoint"] not in {"wake", "button"}:
        raise ValueError("entrypoint is unsupported")
    if event_type == "listening.stopped" and payload["reason"] not in {"end_of_speech", "result_received"}:
        raise ValueError("listening stop reason is unsupported")
    if event_type in {"listening.failed", "transcript.failed"}:
        code = payload["error_code"]
        if not isinstance(code, int) or isinstance(code, bool) or code < 0:
            raise ValueError("error_code must be non-negative integer")
    if event_type in {"transcript.partial", "transcript.final"}:
        text = payload["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("transcript text must be non-empty")
        if value["privacy_class"] != "sensitive":
            raise ValueError("transcript text must be sensitive")
    elif value["privacy_class"] != "household":
        raise ValueError("non-transcript recognizer lifecycle must be household")
    return value
