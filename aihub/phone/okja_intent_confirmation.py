#!/usr/bin/env python3
"""Structured intent and explicit confirmation lifecycle for the live phone bridge."""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from okja_event_contract import new_event, parse_transcript_request, validate_event

INTENT_TYPES = frozenset({
    "intent.requested", "intent.resolved", "intent.failed",
    "confirmation.requested", "confirmation.accepted", "confirmation.rejected",
})

DEVICE_INTENTS = {
    "tv.power_on": ("tv", "power_on"),
    "tv.power_off": ("tv", "power_off"),
    "ac.power_on": ("ac", "power_on"),
    "ac.power_off": ("ac", "power_off"),
    "phone_finder.ring": ("phone_finder", "ring"),
}

_CONFIRM = frozenset({"확인", "확인해", "진행", "진행해", "confirm", "yes confirm", "proceed"})
_CANCEL = frozenset({"취소", "취소해", "하지마", "하지 마", "cancel", "no cancel"})

_DEVICE_PATTERNS = (
    (re.compile(r"(?:tv|티비|텔레비전).*(?:켜|켜줘|켜 줘|turn on|power on)", re.I), "tv.power_on"),
    (re.compile(r"(?:tv|티비|텔레비전).*(?:꺼|꺼줘|꺼 줘|turn off|power off)", re.I), "tv.power_off"),
    (re.compile(r"(?:에어컨|air ?conditioner|ac).*(?:켜|켜줘|켜 줘|turn on|power on)", re.I), "ac.power_on"),
    (re.compile(r"(?:에어컨|air ?conditioner|ac).*(?:꺼|꺼줘|꺼 줘|turn off|power off)", re.I), "ac.power_off"),
    (re.compile(r"(?:휴대폰|핸드폰|내 폰|my phone|phone).*(?:찾아|찾아줘|찾아 줘|find|ring)", re.I), "phone_finder.ring"),
)

# A phrase that explicitly negates the requested action must never be promoted to a
# device command. These patterns intentionally stay narrow: ambiguous language falls
# through to the assistant instead of creating a confirmation for a possibly unsafe act.
_DEVICE_NEGATION_PATTERNS = (
    re.compile(r"(?:켜|켜줘|켜 줘|꺼|꺼줘|꺼 줘|찾아|찾아줘|찾아 줘)\s*(?:지\s*)?마(?:라|세요|줘)?", re.I),
    re.compile(r"(?:하지|하지는)\s*마(?:라|세요|줘)?", re.I),
    re.compile(r"\b(?:do not|don't|dont|never)\b.*\b(?:turn|power|ring|find)\b", re.I),
)

_PAYLOAD_FIELDS = {
    "intent.requested": frozenset({"language"}),
    "intent.resolved": frozenset({"intent_kind", "requires_confirmation", "target", "action"}),
    "intent.failed": frozenset({"reason"}),
    "confirmation.requested": frozenset({"target", "action", "expires_in_seconds"}),
    "confirmation.accepted": frozenset({"target", "action", "reason"}),
    "confirmation.rejected": frozenset({"target", "action", "reason"}),
}


def validate_intent_confirmation_event(event: Mapping[str, Any]) -> dict[str, Any]:
    value = validate_event(event)
    event_type = value["event_type"]
    if event_type not in INTENT_TYPES:
        raise ValueError("event is not an intent/confirmation lifecycle event")
    if value["source"] != "bridge.intent":
        raise ValueError("intent/confirmation source must be bridge.intent")
    if value["privacy_class"] != "personal" or value["retention_class"] != "volatile":
        raise ValueError("intent/confirmation events must be personal and volatile")
    payload = value["payload"]
    if set(payload) != _PAYLOAD_FIELDS[event_type]:
        raise ValueError(f"{event_type} payload fields are not exact")

    if event_type == "intent.requested":
        if payload["language"] not in {"ko-KR", "en-US"}:
            raise ValueError("unsupported intent language")
    elif event_type == "intent.resolved":
        if payload["intent_kind"] not in {"assistant.query", "device.command", "confirmation.response"}:
            raise ValueError("unsupported intent kind")
        if not isinstance(payload["requires_confirmation"], bool):
            raise ValueError("requires_confirmation must be boolean")
        target, action = payload["target"], payload["action"]
        if payload["intent_kind"] == "device.command":
            if (target, action) not in set(DEVICE_INTENTS.values()) or not payload["requires_confirmation"]:
                raise ValueError("device command intent must name a supported action and require confirmation")
        elif payload["intent_kind"] == "confirmation.response":
            if (target, action) not in set(DEVICE_INTENTS.values()) or payload["requires_confirmation"]:
                raise ValueError("confirmation response must reference a supported action without nesting confirmation")
        elif target is not None or action is not None or payload["requires_confirmation"]:
            raise ValueError("assistant.query must not carry target/action or require confirmation")
    elif event_type == "intent.failed":
        if payload["reason"] not in {"confirmation_response_unrecognized"}:
            raise ValueError("unsupported intent failure reason")
    else:
        if (payload["target"], payload["action"]) not in set(DEVICE_INTENTS.values()):
            raise ValueError("confirmation must reference a supported action")
        if event_type == "confirmation.requested":
            seconds = payload["expires_in_seconds"]
            if not isinstance(seconds, int) or isinstance(seconds, bool) or not 5 <= seconds <= 300:
                raise ValueError("confirmation expiry must be 5..300 seconds")
        elif event_type == "confirmation.accepted":
            if payload["reason"] != "explicit_confirm":
                raise ValueError("unsupported confirmation acceptance reason")
        elif payload["reason"] not in {"explicit_cancel", "expired"}:
            raise ValueError("unsupported confirmation rejection reason")
    return value


class VolatileEventLedger:
    """Bounded in-memory bridge ledger; never persists transcript or intent data."""

    def __init__(self, capacity: int = 128):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)

    def record(self, event: Mapping[str, Any]) -> dict[str, Any]:
        value = validate_intent_confirmation_event(event)
        self._events.append(value)
        return value

    def snapshot(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._events]


@dataclass
class _PendingConfirmation:
    confirmation_event_id: str
    target: str
    action: str
    expires_at_ms: float


class VoiceIntentSession:
    """Deterministic live-bridge intent router with explicit two-turn confirmation."""

    def __init__(self, *, confirmation_ttl_seconds: int = 60, ledger_capacity: int = 128):
        if not 5 <= confirmation_ttl_seconds <= 300:
            raise ValueError("confirmation_ttl_seconds must be 5..300")
        self.confirmation_ttl_seconds = confirmation_ttl_seconds
        self.ledger = VolatileEventLedger(ledger_capacity)
        self._pending: dict[tuple[str, str, str, str], _PendingConfirmation] = {}

    @staticmethod
    def _key(request: Mapping[str, Any]) -> tuple[str, str, str, str]:
        # Confirmation is a conversation-local capability. A confirmation from an old
        # correlation must not be accepted by a newly started interaction in the same
        # device/profile/session.
        return (
            request["device_id"],
            request["profile_id"],
            request["session_id"],
            request["correlation_id"],
        )

    @staticmethod
    def _normalized(text: str) -> str:
        return " ".join(text.strip().lower().split())

    def _prune_expired(self, current_ms: float, *, keep_key: tuple[str, str, str, str] | None = None) -> None:
        # Expired confirmations from abandoned correlations have no valid current
        # envelope to which a rejection event could be causally attached. Remove them
        # silently; the current correlation still receives an explicit expired event.
        stale = [
            key for key, pending in self._pending.items()
            if key != keep_key and current_ms > pending.expires_at_ms
        ]
        for key in stale:
            del self._pending[key]

    def _event(
        self,
        request: Mapping[str, Any],
        event_type: str,
        payload: dict[str, Any],
        *,
        causation_id: str | None,
        severity: str = "info",
    ) -> dict[str, Any]:
        event = new_event(
            event_type=event_type,
            device_id=request["device_id"],
            profile_id=request["profile_id"],
            session_id=request["session_id"],
            correlation_id=request["correlation_id"],
            causation_id=causation_id,
            source="bridge.intent",
            severity=severity,
            privacy_class="personal",
            retention_class="volatile",
            payload=payload,
        )
        return self.ledger.record(event)

    def _classify_device(self, text: str) -> tuple[str, str] | None:
        if any(pattern.search(text) for pattern in _DEVICE_NEGATION_PATTERNS):
            return None
        for pattern, intent_name in _DEVICE_PATTERNS:
            if pattern.search(text):
                return DEVICE_INTENTS[intent_name]
        return None

    def process(self, transcript_event: Mapping[str, Any], *, now_ms: float | None = None) -> dict[str, Any]:
        req = parse_transcript_request(transcript_event)
        request = req["envelope"]
        text = req["text"]
        current_ms = time.monotonic() * 1000.0 if now_ms is None else float(now_ms)
        events: list[dict[str, Any]] = []
        key = self._key(request)
        self._prune_expired(current_ms, keep_key=key)

        pending = self._pending.get(key)
        if pending is not None and current_ms > pending.expires_at_ms:
            expired = self._event(
                request,
                "confirmation.rejected",
                {"target": pending.target, "action": pending.action, "reason": "expired"},
                causation_id=pending.confirmation_event_id,
                severity="notice",
            )
            events.append(expired)
            del self._pending[key]
            pending = None

        requested = self._event(
            request,
            "intent.requested",
            {"language": req["language"]},
            causation_id=request["event_id"],
        )
        events.append(requested)

        normalized = self._normalized(text)
        if pending is not None:
            if normalized in _CONFIRM:
                resolved = self._event(
                    request,
                    "intent.resolved",
                    {
                        "intent_kind": "confirmation.response",
                        "requires_confirmation": False,
                        "target": pending.target,
                        "action": pending.action,
                    },
                    causation_id=requested["event_id"],
                )
                accepted = self._event(
                    request,
                    "confirmation.accepted",
                    {"target": pending.target, "action": pending.action, "reason": "explicit_confirm"},
                    causation_id=pending.confirmation_event_id,
                    severity="notice",
                )
                events.extend([resolved, accepted])
                del self._pending[key]
                return {"kind": "confirmation_accepted", "target": pending.target, "action": pending.action, "events": events}

            if normalized in _CANCEL:
                resolved = self._event(
                    request,
                    "intent.resolved",
                    {
                        "intent_kind": "confirmation.response",
                        "requires_confirmation": False,
                        "target": pending.target,
                        "action": pending.action,
                    },
                    causation_id=requested["event_id"],
                )
                rejected = self._event(
                    request,
                    "confirmation.rejected",
                    {"target": pending.target, "action": pending.action, "reason": "explicit_cancel"},
                    causation_id=pending.confirmation_event_id,
                    severity="notice",
                )
                events.extend([resolved, rejected])
                del self._pending[key]
                return {"kind": "confirmation_rejected", "target": pending.target, "action": pending.action, "events": events}

            failed = self._event(
                request,
                "intent.failed",
                {"reason": "confirmation_response_unrecognized"},
                causation_id=requested["event_id"],
                severity="notice",
            )
            events.append(failed)
            return {"kind": "confirmation_retry", "target": pending.target, "action": pending.action, "events": events}

        device = self._classify_device(text)
        if device is not None:
            target, action = device
            resolved = self._event(
                request,
                "intent.resolved",
                {
                    "intent_kind": "device.command",
                    "requires_confirmation": True,
                    "target": target,
                    "action": action,
                },
                causation_id=requested["event_id"],
            )
            confirmation = self._event(
                request,
                "confirmation.requested",
                {"target": target, "action": action, "expires_in_seconds": self.confirmation_ttl_seconds},
                causation_id=resolved["event_id"],
                severity="notice",
            )
            events.extend([resolved, confirmation])
            self._pending[key] = _PendingConfirmation(
                confirmation_event_id=confirmation["event_id"],
                target=target,
                action=action,
                expires_at_ms=current_ms + self.confirmation_ttl_seconds * 1000.0,
            )
            return {"kind": "confirmation_requested", "target": target, "action": action, "events": events}

        resolved = self._event(
            request,
            "intent.resolved",
            {
                "intent_kind": "assistant.query",
                "requires_confirmation": False,
                "target": None,
                "action": None,
            },
            causation_id=requested["event_id"],
        )
        events.append(resolved)
        return {"kind": "assistant_query", "events": events}
