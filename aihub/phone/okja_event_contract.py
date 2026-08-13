#!/usr/bin/env python3
"""Versioned Okja event-envelope contract shared by bridge-side producers.

The Android implementation mirrors these fields. This module is dependency
free so the phone bridge can validate every packet before invoking an agent.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import time
import uuid
from typing import Any, Mapping


SCHEMA_VERSION = "okja.event.v1"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
EVENT_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")

SEVERITIES = frozenset({"debug", "info", "notice", "warning", "error", "critical"})
PRIVACY_CLASSES = frozenset({
    "public", "household", "personal", "sensitive", "health", "emergency"
})
RETENTION_CLASSES = frozenset({
    "volatile", "diagnostic_7d", "history_30d", "user_record",
    "benchmark_fixed", "audit"
})

# Registry covers the stable v1 namespace. Presence here defines the contract;
# it does not claim that every flow is already emitted in the product.
EVENT_TYPES = frozenset({
    "wake.candidate", "wake.detected", "wake.rejected",
    "listening.started", "listening.stopped", "listening.failed",
    "transcript.partial", "transcript.final", "transcript.failed",
    "intent.requested", "intent.resolved", "intent.failed",
    "confirmation.requested", "confirmation.accepted", "confirmation.rejected",
    "command.accepted", "command.completed", "command.failed",
    "assistant.response", "assistant.failed",
    "tts.started", "tts.completed", "tts.failed",
})

REQUIRED_FIELDS = frozenset({
    "schema_version", "event_id", "event_type", "occurred_at",
    "monotonic_ms", "device_id", "profile_id", "session_id",
    "correlation_id", "causation_id", "source", "severity",
    "privacy_class", "retention_class", "payload",
})


def _validate_id(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{field} must match {ID_RE.pattern}")
    return value


def _validate_occurred_at(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("occurred_at must be a UTC RFC3339 timestamp ending in Z")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("occurred_at must be a valid RFC3339 timestamp") from exc
    if parsed.utcoffset() != dt.timedelta(0):
        raise ValueError("occurred_at must be UTC")
    return value


def validate_event(event: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        raise ValueError("event must be an object")
    missing = sorted(REQUIRED_FIELDS - set(event))
    extra = sorted(set(event) - REQUIRED_FIELDS)
    if missing:
        raise ValueError(f"event missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"event has unknown fields: {', '.join(extra)}")
    if event["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
    try:
        uuid.UUID(str(event["event_id"]))
    except (ValueError, AttributeError) as exc:
        raise ValueError("event_id must be a UUID") from exc
    event_type = event["event_type"]
    if not isinstance(event_type, str) or not EVENT_TYPE_RE.fullmatch(event_type):
        raise ValueError("event_type has invalid syntax")
    if event_type not in EVENT_TYPES:
        raise ValueError(f"event_type is not registered for v1: {event_type}")
    _validate_occurred_at(event["occurred_at"])
    monotonic_ms = event["monotonic_ms"]
    if (
        not isinstance(monotonic_ms, (int, float))
        or isinstance(monotonic_ms, bool)
        or not math.isfinite(monotonic_ms)
        or monotonic_ms < 0
    ):
        raise ValueError("monotonic_ms must be a finite non-negative number")
    for field in ("device_id", "profile_id", "session_id", "correlation_id"):
        _validate_id(event[field], field)
    _validate_id(event["causation_id"], "causation_id", nullable=True)
    source = event["source"]
    if not isinstance(source, str) or not SOURCE_RE.fullmatch(source):
        raise ValueError("source has invalid syntax")
    if event["severity"] not in SEVERITIES:
        raise ValueError("severity is not registered")
    if event["privacy_class"] not in PRIVACY_CLASSES:
        raise ValueError("privacy_class is not registered")
    if event["retention_class"] not in RETENTION_CLASSES:
        raise ValueError("retention_class is not registered")
    if not isinstance(event["payload"], dict):
        raise ValueError("payload must be an object")
    return dict(event)


def new_event(
    *,
    event_type: str,
    device_id: str,
    profile_id: str,
    session_id: str,
    correlation_id: str,
    source: str,
    severity: str = "info",
    privacy_class: str = "personal",
    retention_class: str = "volatile",
    causation_id: str | None = None,
    payload: dict[str, Any] | None = None,
    monotonic_ms: float | None = None,
    occurred_at: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    event = {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": occurred_at or now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "monotonic_ms": monotonic_ms if monotonic_ms is not None else time.monotonic() * 1000.0,
        "device_id": device_id,
        "profile_id": profile_id,
        "session_id": session_id,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "source": source,
        "severity": severity,
        "privacy_class": privacy_class,
        "retention_class": retention_class,
        "payload": payload or {},
    }
    return validate_event(event)


def parse_transcript_request(event: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_event(event)
    if validated["event_type"] != "transcript.final":
        raise ValueError("bridge request event_type must be transcript.final")
    if validated["source"] != "android.voice":
        raise ValueError("bridge request source must be android.voice")
    if validated["privacy_class"] != "sensitive":
        raise ValueError("transcript.final privacy_class must be sensitive")
    if validated["retention_class"] != "volatile":
        raise ValueError("transcript.final retention_class must be volatile")
    payload = validated["payload"]
    expected = {"profile", "language", "text"}
    if set(payload) != expected:
        raise ValueError("transcript.final payload must contain only profile, language and text")
    if payload["profile"] not in {"grandma", "personal"}:
        raise ValueError("unsupported profile")
    if payload["language"] not in {"ko-KR", "en-US"}:
        raise ValueError("unsupported language")
    if not isinstance(payload["text"], str):
        raise ValueError("transcript text must be a string")
    if validated["profile_id"] != f"profile-{payload['profile']}":
        raise ValueError("profile_id does not match payload.profile")
    return {
        "envelope": validated,
        "profile": payload["profile"],
        "language": payload["language"],
        "text": payload["text"].strip(),
    }


def assistant_response(request: Mapping[str, Any], text: str) -> dict[str, Any]:
    req = validate_event(request)
    return new_event(
        event_type="assistant.response",
        device_id=req["device_id"],
        profile_id=req["profile_id"],
        session_id=req["session_id"],
        correlation_id=req["correlation_id"],
        causation_id=req["event_id"],
        source="bridge.agent",
        severity="info",
        privacy_class="personal",
        retention_class="volatile",
        payload={"text": str(text)},
    )


def assistant_failure(request: Mapping[str, Any], code: str, message: str) -> dict[str, Any]:
    req = validate_event(request)
    return new_event(
        event_type="assistant.failed",
        device_id=req["device_id"],
        profile_id=req["profile_id"],
        session_id=req["session_id"],
        correlation_id=req["correlation_id"],
        causation_id=req["event_id"],
        source="bridge.agent",
        severity="error",
        privacy_class="personal",
        retention_class="volatile",
        payload={"error_code": str(code), "message": str(message)},
    )


def parse_assistant_result(
    event: Mapping[str, Any], request: Mapping[str, Any]
) -> dict[str, Any]:
    result = validate_event(event)
    req = validate_event(request)
    if result["event_type"] not in {"assistant.response", "assistant.failed"}:
        raise ValueError("unexpected assistant result event_type")
    if result["source"] != "bridge.agent":
        raise ValueError("assistant result source must be bridge.agent")
    if result["privacy_class"] != "personal" or result["retention_class"] != "volatile":
        raise ValueError("assistant result must be personal and volatile")
    for field in ("device_id", "profile_id", "session_id", "correlation_id"):
        if result[field] != req[field]:
            raise ValueError(f"assistant result {field} mismatch")
    if result["causation_id"] != req["event_id"]:
        raise ValueError("assistant result causation_id mismatch")
    if result["event_type"] == "assistant.response":
        if result["severity"] != "info" or set(result["payload"]) != {"text"}:
            raise ValueError("assistant.response must have info severity and text-only payload")
        if not isinstance(result["payload"]["text"], str):
            raise ValueError("assistant.response payload.text must be a string")
    else:
        if result["severity"] != "error" or set(result["payload"]) != {"error_code", "message"}:
            raise ValueError("assistant.failed must have error severity and exact error payload")
        if not all(isinstance(result["payload"][key], str) for key in ("error_code", "message")):
            raise ValueError("assistant.failed error fields must be strings")
    return result
