#!/usr/bin/env python3
"""Validated, durable, at-most-once Okja device-command boundary."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from okja_event_contract import new_event


SCHEMA_VERSION = "okja.device-command.v1"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
COMMAND_FIELDS = frozenset({
    "schema_version", "command_id", "idempotency_key", "issued_at",
    "expires_at", "device_id", "profile_id", "session_id",
    "correlation_id", "source_event_id", "target", "action", "parameters",
})

CAPABILITIES: dict[str, dict[str, Any]] = {
    "tv": {
        "enabled": True,
        "runtime": "adapter_required",
        "actions": [
            "power_on", "power_off", "resume_last_source",
            "volume_up", "volume_down", "set_channel",
        ],
    },
    "ac": {
        "enabled": True,
        "runtime": "adapter_required",
        "actions": ["power_on", "power_off", "set_temperature", "set_mode"],
    },
    "phone_finder": {
        "enabled": True,
        "runtime": "adapter_required",
        "actions": ["ring", "cancel"],
    },
    "washer": {
        "enabled": False,
        "runtime": "disabled",
        "actions": ["start", "cancel"],
        "disabled_reason": "reserved_until_physical_integration_exists",
    },
}

Adapter = Callable[[dict[str, Any]], dict[str, Any]]


class IdempotencyConflict(ValueError):
    pass


def capability_manifest() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "capabilities": json.loads(json.dumps(CAPABILITIES, sort_keys=True)),
    }


def _parse_utc(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be a UTC RFC3339 timestamp ending in Z")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be valid RFC3339") from exc
    if parsed.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return parsed


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValueError(f"{field} has invalid syntax")
    return value


def _uuid(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be UUID text")
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a UUID") from exc
    return value


def _exact_parameters(parameters: Any, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(parameters, dict) or set(parameters) != expected:
        raise ValueError(f"{context} parameters must be exactly {sorted(expected)}")
    return dict(parameters)


def _validate_parameters(target: str, action: str, parameters: Any) -> dict[str, Any]:
    context = f"{target}.{action}"
    if action in {
        "power_on", "power_off", "resume_last_source", "cancel", "start"
    }:
        return _exact_parameters(parameters, set(), context)
    if target == "tv" and action in {"volume_up", "volume_down"}:
        out = _exact_parameters(parameters, {"steps"}, context)
        steps = out["steps"]
        if not isinstance(steps, int) or isinstance(steps, bool) or not 1 <= steps <= 10:
            raise ValueError(f"{context}.steps must be an integer from 1 to 10")
        return out
    if target == "tv" and action == "set_channel":
        out = _exact_parameters(parameters, {"channel"}, context)
        channel = out["channel"]
        if not isinstance(channel, str) or not 1 <= len(channel) <= 32:
            raise ValueError(f"{context}.channel must be 1-32 characters")
        return out
    if target == "ac" and action == "set_temperature":
        out = _exact_parameters(parameters, {"celsius"}, context)
        value = out["celsius"]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or not 16 <= value <= 30
        ):
            raise ValueError(f"{context}.celsius must be finite and from 16 to 30")
        return out
    if target == "ac" and action == "set_mode":
        out = _exact_parameters(parameters, {"mode"}, context)
        if out["mode"] not in {"auto", "cool", "dry", "fan"}:
            raise ValueError(f"{context}.mode is unsupported")
        return out
    if target == "phone_finder" and action == "ring":
        out = _exact_parameters(parameters, {"duration_seconds"}, context)
        seconds = out["duration_seconds"]
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 5 <= seconds <= 120:
            raise ValueError(f"{context}.duration_seconds must be an integer from 5 to 120")
        return out
    raise ValueError(f"parameter contract is missing for {context}")


def validate_command(command: Mapping[str, Any], *, now: dt.datetime | None = None) -> dict[str, Any]:
    if not isinstance(command, Mapping):
        raise ValueError("command must be an object")
    missing = sorted(COMMAND_FIELDS - set(command))
    extra = sorted(set(command) - COMMAND_FIELDS)
    if missing:
        raise ValueError(f"command missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"command has unknown fields: {', '.join(extra)}")
    if command["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"schema_version must equal {SCHEMA_VERSION}")
    _uuid(command["command_id"], "command_id")
    _id(command["idempotency_key"], "idempotency_key")
    issued = _parse_utc(command["issued_at"], "issued_at")
    expires = _parse_utc(command["expires_at"], "expires_at")
    if expires <= issued:
        raise ValueError("expires_at must be later than issued_at")
    if expires - issued > dt.timedelta(minutes=5):
        raise ValueError("command validity window cannot exceed five minutes")
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if issued > current + dt.timedelta(seconds=30):
        raise ValueError("command issued_at is too far in the future")
    if current > expires:
        raise ValueError("command has expired")
    for field in ("device_id", "profile_id", "session_id", "correlation_id"):
        _id(command[field], field)
    _uuid(command["source_event_id"], "source_event_id")
    target = command["target"]
    if target not in CAPABILITIES:
        raise ValueError(f"unknown target: {target}")
    action = command["action"]
    if action not in CAPABILITIES[target]["actions"]:
        raise ValueError(f"unsupported action for {target}: {action}")
    normalized = dict(command)
    normalized["parameters"] = _validate_parameters(target, action, command["parameters"])
    return normalized


def _canonical_hash(command: Mapping[str, Any]) -> str:
    raw = json.dumps(command, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DeviceCommandService:
    """Executes each idempotency key at most once and durably caches its result.

    A process interruption after adapter invocation leaves the key in
    `in_progress`; retries do not re-run the physical action automatically.
    This favors at-most-once safety over a potentially duplicated TV/AC action.
    """

    def __init__(self, database: Path, adapters: Mapping[str, Adapter] | None = None):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.adapters = dict(adapters or {})
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._schema_lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS command_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('in_progress', 'complete')),
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )

    def _reserve(self, key: str, request_hash: str) -> tuple[str, dict[str, Any] | None]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_sha256, state, result_json FROM command_idempotency "
                "WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO command_idempotency "
                    "(idempotency_key, request_sha256, state, created_at) "
                    "VALUES (?, ?, 'in_progress', ?)",
                    (key, request_hash, dt.datetime.now(dt.timezone.utc).isoformat()),
                )
                connection.commit()
                return "new", None
            if row["request_sha256"] != request_hash:
                connection.rollback()
                raise IdempotencyConflict(
                    "idempotency_key was already used for a different command")
            if row["state"] == "complete":
                result = json.loads(row["result_json"])
                connection.commit()
                return "replay", result
            connection.commit()
            return "in_progress", None

    def _complete(self, key: str, request_hash: str, result: dict[str, Any]) -> None:
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE command_idempotency SET state='complete', result_json=?, completed_at=? "
                "WHERE idempotency_key=? AND request_sha256=? AND state='in_progress'",
                (
                    serialized,
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                    key,
                    request_hash,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("lost idempotency reservation")

    @staticmethod
    def _event(command: dict[str, Any], event_type: str, causation_id: str,
               severity: str, payload: dict[str, Any]) -> dict[str, Any]:
        return new_event(
            event_type=event_type,
            device_id=command["device_id"],
            profile_id=command["profile_id"],
            session_id=command["session_id"],
            correlation_id=command["correlation_id"],
            causation_id=causation_id,
            source="device.command",
            severity=severity,
            privacy_class="personal",
            retention_class="audit",
            payload=payload,
        )

    def execute(self, command: Mapping[str, Any], *, now: dt.datetime | None = None) -> dict[str, Any]:
        validated = validate_command(command, now=now)
        request_hash = _canonical_hash(validated)
        key = validated["idempotency_key"]
        reservation, cached = self._reserve(key, request_hash)
        if reservation == "replay":
            return {**cached, "replayed": True}
        if reservation == "in_progress":
            return {
                "schema_version": SCHEMA_VERSION,
                "idempotency_key": key,
                "state": "in_progress",
                "replayed": True,
                "accepted_event": None,
                "terminal_event": None,
            }

        capability = CAPABILITIES[validated["target"]]
        adapter = self.adapters.get(validated["target"])
        base_payload = {
            "command_id": validated["command_id"],
            "idempotency_key": key,
            "target": validated["target"],
            "action": validated["action"],
        }
        accepted = None
        if not capability["enabled"]:
            terminal = self._event(
                validated, "command.failed", validated["source_event_id"], "warning",
                {**base_payload, "error_code": "capability_disabled",
                 "retryable": False, "reason": capability["disabled_reason"]},
            )
        elif adapter is None:
            terminal = self._event(
                validated, "command.failed", validated["source_event_id"], "error",
                {**base_payload, "error_code": "adapter_unavailable",
                 "retryable": True, "reason": "runtime adapter is not configured"},
            )
        else:
            accepted = self._event(
                validated, "command.accepted", validated["source_event_id"], "info",
                {**base_payload, "parameters": validated["parameters"]},
            )
            try:
                output = adapter(validated)
                if not isinstance(output, dict):
                    raise TypeError("adapter result must be an object")
                json.dumps(output, ensure_ascii=False, allow_nan=False)
                terminal = self._event(
                    validated, "command.completed", accepted["event_id"], "info",
                    {**base_payload, "output": output},
                )
            except Exception as exc:
                terminal = self._event(
                    validated, "command.failed", accepted["event_id"], "error",
                    {**base_payload, "error_code": "adapter_failed", "retryable": False,
                     "reason": type(exc).__name__},
                )

        result = {
            "schema_version": SCHEMA_VERSION,
            "idempotency_key": key,
            "state": "complete",
            "replayed": False,
            "accepted_event": accepted,
            "terminal_event": terminal,
        }
        self._complete(key, request_hash, result)
        return result
