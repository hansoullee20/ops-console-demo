#!/usr/bin/env python3
"""Shared fail-closed senior/personal profile and consent contract."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEMA_VERSION = "okja.profile.v1"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
PROFILE_FIELDS = frozenset({
    "schema_version", "profile_id", "mode", "display_name", "locale",
    "timezone", "accessibility", "device_capabilities",
    "caregiver_notifications", "consents", "created_at", "updated_at",
})
ACCESSIBILITY_FIELDS = frozenset({
    "text_scale", "minimum_touch_target_dp", "calendar_display",
    "quiet_hours", "night_mode", "quick_actions",
})
QUIET_HOURS_FIELDS = frozenset({"enabled", "start_local", "end_local"})
NIGHT_MODE_FIELDS = frozenset({"enabled", "screen_off", "local_wake_available"})
CAPABILITY_FIELDS = frozenset({"tv", "ac", "phone_finder", "washer"})
NOTIFICATION_FIELDS = frozenset({
    "enabled", "recipients", "events", "quiet_hours_respected",
    "emergency_overrides_quiet_hours",
})
NOTIFICATION_EVENT_FIELDS = frozenset({
    "wellness", "symptom_journal", "arrival_departure", "inactivity", "emergency",
})
RECIPIENT_FIELDS = frozenset({"caregiver_id", "channels"})
CONSENT_FIELDS = frozenset({
    "essential_product", "health_journal", "caregiver_sharing",
    "camera", "benchmark_research",
})
CONSENT_RECORD_FIELDS = frozenset({"status", "policy_version", "updated_at"})

MODES = frozenset({"senior", "personal"})
LOCALES = frozenset({"ko-KR", "en-US"})
TEXT_SCALES = frozenset({"standard", "large", "extra_large"})
CALENDAR_DISPLAYS = frozenset({"solar", "lunar", "both"})
QUICK_ACTIONS = frozenset({
    "tv", "ac", "phone_finder", "call_family", "medication", "emergency",
})
NOTIFICATION_CHANNELS = frozenset({"push", "sms", "call"})
CONSENT_STATUSES = frozenset({"unset", "granted", "declined"})


def _exact(value: Any, expected: frozenset[str], context: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        raise ValueError(f"{context} missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"{context} has unknown fields: {', '.join(extra)}")
    return dict(value)


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{field} has invalid syntax")
    return value


def _utc(value: Any, field: str, *, nullable: bool = False) -> dt.datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be UTC RFC3339 ending in Z")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be valid RFC3339") from exc
    if parsed.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return parsed


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def _consent_record(value: Any, field: str) -> dict[str, Any]:
    record = _exact(value, CONSENT_RECORD_FIELDS, field)
    status = record["status"]
    if status not in CONSENT_STATUSES:
        raise ValueError(f"{field}.status is unsupported")
    policy = record["policy_version"]
    updated = record["updated_at"]
    if status == "unset":
        if policy != "" or updated is not None:
            raise ValueError(f"{field} unset record must have blank policy and null timestamp")
    else:
        if not isinstance(policy, str) or not 1 <= len(policy) <= 64:
            raise ValueError(f"{field}.policy_version must be 1-64 characters")
        _utc(updated, f"{field}.updated_at")
    return record


def validate_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    result = _exact(profile, PROFILE_FIELDS, "profile")
    if result["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
    _id(result["profile_id"], "profile_id")
    mode = result["mode"]
    if mode not in MODES:
        raise ValueError("mode must be senior or personal")
    if not isinstance(result["display_name"], str) or not 1 <= len(result["display_name"].strip()) <= 80:
        raise ValueError("display_name must contain 1-80 visible characters")
    if result["locale"] not in LOCALES:
        raise ValueError("locale is unsupported")
    if not isinstance(result["timezone"], str):
        raise ValueError("timezone must be text")
    try:
        ZoneInfo(result["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be an IANA timezone") from exc
    created = _utc(result["created_at"], "created_at")
    updated = _utc(result["updated_at"], "updated_at")
    if updated < created:
        raise ValueError("updated_at cannot precede created_at")

    accessibility = _exact(result["accessibility"], ACCESSIBILITY_FIELDS, "accessibility")
    if accessibility["text_scale"] not in TEXT_SCALES:
        raise ValueError("accessibility.text_scale is unsupported")
    target_dp = accessibility["minimum_touch_target_dp"]
    if not isinstance(target_dp, int) or isinstance(target_dp, bool) or not 48 <= target_dp <= 120:
        raise ValueError("minimum_touch_target_dp must be an integer from 48 to 120")
    if accessibility["calendar_display"] not in CALENDAR_DISPLAYS:
        raise ValueError("calendar_display is unsupported")
    quiet = _exact(accessibility["quiet_hours"], QUIET_HOURS_FIELDS, "quiet_hours")
    _bool(quiet["enabled"], "quiet_hours.enabled")
    for field in ("start_local", "end_local"):
        if not isinstance(quiet[field], str) or not TIME_RE.fullmatch(quiet[field]):
            raise ValueError(f"quiet_hours.{field} must be HH:MM")
    if quiet["start_local"] == quiet["end_local"]:
        raise ValueError("quiet hours start and end cannot be equal")
    night = _exact(accessibility["night_mode"], NIGHT_MODE_FIELDS, "night_mode")
    for field in NIGHT_MODE_FIELDS:
        _bool(night[field], f"night_mode.{field}")
    if night["screen_off"] and not night["enabled"]:
        raise ValueError("night_mode.screen_off requires night mode enabled")
    actions = accessibility["quick_actions"]
    if not isinstance(actions, list) or not all(action in QUICK_ACTIONS for action in actions):
        raise ValueError("quick_actions contains an unsupported value")
    if len(actions) != len(set(actions)) or len(actions) > 6:
        raise ValueError("quick_actions must be unique with at most six entries")
    if mode == "senior":
        if accessibility["text_scale"] not in {"large", "extra_large"}:
            raise ValueError("senior profile requires large or extra-large text")
        if target_dp < 64:
            raise ValueError("senior profile requires at least 64dp touch targets")

    capabilities = _exact(
        result["device_capabilities"], CAPABILITY_FIELDS, "device_capabilities"
    )
    for field in CAPABILITY_FIELDS:
        _bool(capabilities[field], f"device_capabilities.{field}")
    if capabilities["washer"]:
        raise ValueError("washer capability is reserved and must remain false")
    for action in {"tv", "ac", "phone_finder"}.intersection(actions):
        if not capabilities[action]:
            raise ValueError(f"quick action {action} requires its capability")

    consents_raw = _exact(result["consents"], CONSENT_FIELDS, "consents")
    consents = {
        field: _consent_record(consents_raw[field], f"consents.{field}")
        for field in CONSENT_FIELDS
    }

    notifications = _exact(
        result["caregiver_notifications"], NOTIFICATION_FIELDS,
        "caregiver_notifications",
    )
    enabled = _bool(notifications["enabled"], "caregiver_notifications.enabled")
    quiet_respected = _bool(
        notifications["quiet_hours_respected"],
        "caregiver_notifications.quiet_hours_respected",
    )
    emergency_override = _bool(
        notifications["emergency_overrides_quiet_hours"],
        "caregiver_notifications.emergency_overrides_quiet_hours",
    )
    events = _exact(
        notifications["events"], NOTIFICATION_EVENT_FIELDS,
        "caregiver_notifications.events",
    )
    for field in NOTIFICATION_EVENT_FIELDS:
        _bool(events[field], f"caregiver_notifications.events.{field}")
    recipients = notifications["recipients"]
    if not isinstance(recipients, list):
        raise ValueError("caregiver_notifications.recipients must be a list")
    seen_recipients: set[str] = set()
    for index, value in enumerate(recipients):
        recipient = _exact(value, RECIPIENT_FIELDS, f"recipients[{index}]")
        caregiver_id = _id(recipient["caregiver_id"], f"recipients[{index}].caregiver_id")
        if caregiver_id in seen_recipients:
            raise ValueError("caregiver recipient IDs must be unique")
        seen_recipients.add(caregiver_id)
        channels = recipient["channels"]
        if (
            not isinstance(channels, list)
            or not channels
            or not all(channel in NOTIFICATION_CHANNELS for channel in channels)
            or len(channels) != len(set(channels))
        ):
            raise ValueError("recipient channels must be a non-empty unique allowed list")
    if enabled:
        if not recipients:
            raise ValueError("enabled caregiver notifications require a recipient")
        if consents["caregiver_sharing"]["status"] != "granted":
            raise ValueError("caregiver notifications require caregiver-sharing consent")
        if (events["wellness"] or events["symptom_journal"]) and (
            consents["health_journal"]["status"] != "granted"
        ):
            raise ValueError("health notifications require health-journal consent")
    elif recipients or any(events.values()):
        raise ValueError("disabled caregiver notifications cannot retain recipients or event flags")
    if emergency_override and not (enabled and events["emergency"]):
        raise ValueError("emergency quiet-hours override requires enabled emergency notifications")
    if not quiet_respected and enabled and not emergency_override:
        raise ValueError("quiet hours may only be bypassed for enabled emergency notifications")
    return result


def _unset_consent() -> dict[str, Any]:
    return {"status": "unset", "policy_version": "", "updated_at": None}


def create_profile(
    *, profile_id: str, mode: str, display_name: str,
    locale: str = "ko-KR", timezone: str = "Asia/Seoul",
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    timestamp = current.astimezone(dt.timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    senior = mode == "senior"
    profile = {
        "schema_version": SCHEMA_VERSION,
        "profile_id": profile_id,
        "mode": mode,
        "display_name": display_name,
        "locale": locale,
        "timezone": timezone,
        "accessibility": {
            "text_scale": "extra_large" if senior else "standard",
            "minimum_touch_target_dp": 72 if senior else 48,
            "calendar_display": "both" if senior else "solar",
            "quiet_hours": {
                "enabled": senior,
                "start_local": "21:00",
                "end_local": "07:00",
            },
            "night_mode": {
                "enabled": senior,
                "screen_off": senior,
                "local_wake_available": True,
            },
            "quick_actions": ["tv", "ac", "phone_finder"] if senior else [],
        },
        "device_capabilities": {
            "tv": True,
            "ac": True,
            "phone_finder": True,
            "washer": False,
        },
        "caregiver_notifications": {
            "enabled": False,
            "recipients": [],
            "events": {field: False for field in sorted(NOTIFICATION_EVENT_FIELDS)},
            "quiet_hours_respected": True,
            "emergency_overrides_quiet_hours": False,
        },
        "consents": {field: _unset_consent() for field in sorted(CONSENT_FIELDS)},
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return validate_profile(profile)
