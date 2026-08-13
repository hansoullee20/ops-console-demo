#!/usr/bin/env python3
"""Typed, consent-aware care and family events on okja.event.v1."""

from __future__ import annotations

import math
import re
import uuid
from typing import Any, Mapping

from okja_event_contract import new_event, validate_event
from okja_profile_config import validate_profile


CARE_EVENT_TYPES = frozenset({
    "wellness.checkin_requested", "wellness.checkin_recorded",
    "symptom.recorded", "presence.arrived", "presence.departed",
    "family.eta_updated", "notification.requested",
    "notification.delivered", "notification.failed",
})
AGENT_SOURCES = frozenset({"agent", "llm", "assistant", "bridge.agent"})
SOURCE_ALLOWLISTS = {
    "wellness.checkin_requested": frozenset({"care.scheduler", "care.ui"}),
    "wellness.checkin_recorded": frozenset({"care.ui", "android.care"}),
    "symptom.recorded": frozenset({"care.ui", "android.care"}),
    "presence.arrived": frozenset({"sensor.fusion", "care.ui"}),
    "presence.departed": frozenset({"sensor.fusion", "care.ui"}),
    "family.eta_updated": frozenset({"family.app", "personal.ui"}),
    "notification.requested": frozenset({"care.notification_policy"}),
    "notification.delivered": frozenset({"notification.dispatcher"}),
    "notification.failed": frozenset({"notification.dispatcher"}),
}
POLICIES = {
    "wellness.checkin_requested": ("personal", "history_30d", "info"),
    "wellness.checkin_recorded": ("health", "user_record", "info"),
    "symptom.recorded": ("health", "user_record", "notice"),
    "presence.arrived": ("personal", "history_30d", "info"),
    "presence.departed": ("personal", "history_30d", "info"),
    "family.eta_updated": ("household", "history_30d", "info"),
    "notification.requested": ("personal", "audit", "info"),
    "notification.delivered": ("personal", "audit", "info"),
    "notification.failed": ("personal", "audit", "warning"),
}
PAYLOAD_FIELDS = {
    "wellness.checkin_requested": frozenset({
        "prompt_id", "scheduled_for", "can_snooze", "can_decline",
    }),
    "wellness.checkin_recorded": frozenset({"prompt_id", "response", "note"}),
    "symptom.recorded": frozenset({
        "record_id", "reported_text", "body_area", "self_reported_severity",
        "sharing_requested",
    }),
    "presence.arrived": frozenset({
        "person_profile_id", "home_id", "observed_at", "estimate_status",
        "confidence", "evidence_sources",
    }),
    "presence.departed": frozenset({
        "person_profile_id", "home_id", "observed_at", "estimate_status",
        "confidence", "evidence_sources",
    }),
    "family.eta_updated": frozenset({
        "sender_profile_id", "recipient_profile_id", "eta_minutes", "status", "message",
    }),
    "notification.requested": frozenset({
        "notification_id", "subject_event_id", "category", "deliveries", "summary_code",
    }),
    "notification.delivered": frozenset({
        "notification_id", "caregiver_id", "channel", "attempt", "delivered_at",
    }),
    "notification.failed": frozenset({
        "notification_id", "caregiver_id", "channel", "attempt", "error_code", "retryable",
    }),
}
PRESENCE_EVIDENCE = frozenset({
    "door_sensor", "presence_sensor", "phone", "voice", "caregiver", "user",
})
NOTIFICATION_CATEGORIES = frozenset({
    "wellness", "symptom_journal", "arrival_departure", "inactivity",
    "emergency", "family_eta",
})
SUMMARY_CODES_BY_CATEGORY = {
    "wellness": frozenset({"wellness_due"}),
    "symptom_journal": frozenset({"symptom_shared"}),
    "arrival_departure": frozenset({"arrival", "departure"}),
    "inactivity": frozenset({"inactivity"}),
    "emergency": frozenset({"emergency"}),
    "family_eta": frozenset({"family_eta"}),
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _exact(value: Any, fields: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{context} fields must exactly match {sorted(fields)}")
    return dict(value)


def _uuid(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be UUID text")
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID") from exc
    return value


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{field} has invalid syntax")
    return value


def _text(value: Any, field: str, minimum: int, maximum: int,
          *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f"{field} must contain {minimum}-{maximum} visible characters")
    return value


def _utc(value: Any, field: str) -> str:
    from datetime import datetime, timedelta
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be UTC RFC3339 ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be valid RFC3339") from exc
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return value


def _consent(profile: dict[str, Any], name: str) -> bool:
    return profile["consents"][name]["status"] == "granted"


def _configured_recipients(profile: dict[str, Any]) -> dict[str, set[str]]:
    return {
        row["caregiver_id"]: set(row["channels"])
        for row in profile["caregiver_notifications"]["recipients"]
    }


def _validate_payload(event_type: str, payload: Any, profile: dict[str, Any]) -> dict[str, Any]:
    value = _exact(payload, PAYLOAD_FIELDS[event_type], f"{event_type}.payload")
    if event_type == "wellness.checkin_requested":
        _text(value["prompt_id"], "prompt_id", 1, 128)
        _utc(value["scheduled_for"], "scheduled_for")
        if value["can_snooze"] is not True or value["can_decline"] is not True:
            raise ValueError("wellness prompts must allow both snooze and decline")
        if not _consent(profile, "health_journal"):
            raise ValueError("wellness event requires health-journal consent")
    elif event_type == "wellness.checkin_recorded":
        _text(value["prompt_id"], "prompt_id", 1, 128)
        if value["response"] not in {"okay", "not_well", "snoozed", "declined"}:
            raise ValueError("wellness response is unsupported")
        _text(value["note"], "note", 0, 500, nullable=True)
        if not _consent(profile, "health_journal"):
            raise ValueError("wellness record requires health-journal consent")
    elif event_type == "symptom.recorded":
        _uuid(value["record_id"], "record_id")
        _text(value["reported_text"], "reported_text", 1, 1000)
        _text(value["body_area"], "body_area", 1, 80, nullable=True)
        if value["self_reported_severity"] not in {
            "unspecified", "mild", "moderate", "severe"
        }:
            raise ValueError("self_reported_severity is unsupported")
        if not isinstance(value["sharing_requested"], bool):
            raise ValueError("sharing_requested must be boolean")
        if not _consent(profile, "health_journal"):
            raise ValueError("symptom record requires health-journal consent")
        if value["sharing_requested"] and not _consent(profile, "caregiver_sharing"):
            raise ValueError("symptom sharing requires caregiver-sharing consent")
    elif event_type in {"presence.arrived", "presence.departed"}:
        _id(value["person_profile_id"], "person_profile_id")
        _id(value["home_id"], "home_id")
        _utc(value["observed_at"], "observed_at")
        if value["estimate_status"] not in {"estimated", "confirmed", "corrected"}:
            raise ValueError("estimate_status is unsupported")
        confidence = value["confidence"]
        if (
            not isinstance(confidence, (int, float)) or isinstance(confidence, bool)
            or not math.isfinite(confidence) or not 0 <= confidence <= 1
        ):
            raise ValueError("confidence must be finite from 0 to 1")
        evidence = value["evidence_sources"]
        if (
            not isinstance(evidence, list) or not evidence
            or len(evidence) != len(set(evidence))
            or not all(item in PRESENCE_EVIDENCE for item in evidence)
        ):
            raise ValueError("evidence_sources must be a non-empty unique allowed list")
    elif event_type == "family.eta_updated":
        _id(value["sender_profile_id"], "sender_profile_id")
        _id(value["recipient_profile_id"], "recipient_profile_id")
        if value["sender_profile_id"] != profile["profile_id"]:
            raise ValueError("family ETA sender must match envelope profile")
        if value["recipient_profile_id"] == value["sender_profile_id"]:
            raise ValueError("family ETA recipient must differ from sender")
        eta = value["eta_minutes"]
        if not isinstance(eta, int) or isinstance(eta, bool) or not 0 <= eta <= 1440:
            raise ValueError("eta_minutes must be an integer from 0 to 1440")
        if value["status"] not in {"on_the_way", "delayed", "arrived", "cancelled"}:
            raise ValueError("family ETA status is unsupported")
        _text(value["message"], "message", 0, 160, nullable=True)
        if not _consent(profile, "caregiver_sharing"):
            raise ValueError("family ETA requires caregiver-sharing consent")
    elif event_type == "notification.requested":
        _uuid(value["notification_id"], "notification_id")
        _uuid(value["subject_event_id"], "subject_event_id")
        category = value["category"]
        if category not in NOTIFICATION_CATEGORIES:
            raise ValueError("notification category is unsupported")
        if value["summary_code"] not in SUMMARY_CODES_BY_CATEGORY[category]:
            raise ValueError("notification summary_code does not match category")
        notifications = profile["caregiver_notifications"]
        if not notifications["enabled"] or not notifications["events"][category]:
            raise ValueError("notification category is not enabled in the profile")
        if not _consent(profile, "caregiver_sharing"):
            raise ValueError("notification requires caregiver-sharing consent")
        if category in {"wellness", "symptom_journal"} and not _consent(
            profile, "health_journal"
        ):
            raise ValueError("health notification requires health-journal consent")
        configured = _configured_recipients(profile)
        deliveries = value["deliveries"]
        if not isinstance(deliveries, list) or not deliveries:
            raise ValueError("notification deliveries must be non-empty")
        seen: set[tuple[str, str]] = set()
        for index, delivery in enumerate(deliveries):
            row = _exact(
                delivery, frozenset({"caregiver_id", "channel"}), f"deliveries[{index}]"
            )
            caregiver_id = _id(row["caregiver_id"], "caregiver_id")
            channel = row["channel"]
            if caregiver_id not in configured or channel not in configured[caregiver_id]:
                raise ValueError("notification delivery is not configured for the caregiver")
            pair = (caregiver_id, channel)
            if pair in seen:
                raise ValueError("notification deliveries must be unique")
            seen.add(pair)
    else:
        _uuid(value["notification_id"], "notification_id")
        caregiver_id = _id(value["caregiver_id"], "caregiver_id")
        configured = _configured_recipients(profile)
        if caregiver_id not in configured or value["channel"] not in configured[caregiver_id]:
            raise ValueError("notification result caregiver/channel is not configured")
        attempt = value["attempt"]
        if not isinstance(attempt, int) or isinstance(attempt, bool) or not 1 <= attempt <= 20:
            raise ValueError("notification attempt must be an integer from 1 to 20")
        if event_type == "notification.delivered":
            _utc(value["delivered_at"], "delivered_at")
        else:
            _text(value["error_code"], "error_code", 1, 128)
            if not isinstance(value["retryable"], bool):
                raise ValueError("retryable must be boolean")
        if not _consent(profile, "caregiver_sharing"):
            raise ValueError("notification result requires caregiver-sharing consent")
    return value


def validate_care_event(event: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    validated_profile = validate_profile(profile)
    validated = validate_event(event)
    event_type = validated["event_type"]
    if event_type not in CARE_EVENT_TYPES:
        raise ValueError("event_type is not a care/family event")
    if validated["profile_id"] != validated_profile["profile_id"]:
        raise ValueError("event profile_id does not match profile contract")
    source = validated["source"]
    if source in AGENT_SOURCES or source not in SOURCE_ALLOWLISTS[event_type]:
        raise ValueError("event source is not allowed for this care event")
    privacy, retention, severity = POLICIES[event_type]
    if event_type == "notification.requested" and validated["payload"].get("category") == "emergency":
        severity = "critical"
        privacy = "emergency"
    if (
        validated["privacy_class"] != privacy
        or validated["retention_class"] != retention
        or validated["severity"] != severity
    ):
        raise ValueError("care event privacy/retention/severity policy mismatch")
    if validated["causation_id"] is None:
        raise ValueError("care events require a causation_id")
    payload = _validate_payload(event_type, validated["payload"], validated_profile)
    if (
        event_type == "notification.requested"
        and payload["subject_event_id"] != validated["causation_id"]
    ):
        raise ValueError("notification subject_event_id must match causation_id")
    return validated


def new_care_event(
    *, event_type: str, profile: Mapping[str, Any], device_id: str,
    session_id: str, correlation_id: str, causation_id: str,
    source: str, payload: dict[str, Any],
) -> dict[str, Any]:
    validated_profile = validate_profile(profile)
    if event_type not in CARE_EVENT_TYPES:
        raise ValueError("event_type is not a care/family event")
    privacy, retention, severity = POLICIES[event_type]
    if event_type == "notification.requested" and payload.get("category") == "emergency":
        severity = "critical"
        privacy = "emergency"
    event = new_event(
        event_type=event_type,
        device_id=device_id,
        profile_id=validated_profile["profile_id"],
        session_id=session_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        source=source,
        severity=severity,
        privacy_class=privacy,
        retention_class=retention,
        payload=payload,
    )
    return validate_care_event(event, validated_profile)
