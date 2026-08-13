#!/usr/bin/env python3
"""Persisted confirm-before-escalate state machine for Okja emergencies."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from okja_event_contract import new_event


STATES = frozenset({"awaiting_confirmation", "ready_to_escalate", "escalating", "resolved"})
SIGNAL_TYPES = frozenset({"fall_suspected", "manual_sos", "wellness_concern"})
SIGNAL_SOURCES = frozenset({"sensor", "user", "caregiver", "device_button"})
RESPONSE_SOURCES = frozenset({"user", "caregiver", "policy_timer"})
AGENT_SOURCES = frozenset({"agent", "llm", "assistant", "bridge.agent"})
RESPONSES = frozenset({"safe", "needs_help", "timeout"})
ESCALATION_CHANNELS = frozenset({"family_notification"})
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class EmergencyTransitionError(ValueError):
    pass


class EmergencyReplayConflict(ValueError):
    pass


def _utc(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be UTC RFC3339 ending in Z")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be valid RFC3339") from exc
    if parsed.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{field} must be UTC")
    return parsed


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


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _authorization_message(case_id: str, state_version: int, channel: str,
                           expires_at: str, authorization_id: str) -> bytes:
    return "|".join(
        [case_id, str(state_version), channel, expires_at, authorization_id]
    ).encode("utf-8")


def make_policy_authorization(
    policy_secret: bytes,
    *,
    case_id: str,
    state_version: int,
    channel: str,
    expires_at: str,
    authorization_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(policy_secret, bytes) or len(policy_secret) < 32:
        raise ValueError("policy_secret must contain at least 32 bytes")
    auth_id = authorization_id or str(uuid.uuid4())
    signature = hmac.new(
        policy_secret,
        _authorization_message(case_id, state_version, channel, expires_at, auth_id),
        hashlib.sha256,
    ).hexdigest()
    return {
        "authorization_id": auth_id,
        "case_id": case_id,
        "state_version": state_version,
        "channel": channel,
        "expires_at": expires_at,
        "signature": signature,
    }


class EmergencyStateMachine:
    def __init__(self, database: Path, policy_secret: bytes):
        if not isinstance(policy_secret, bytes) or len(policy_secret) < 32:
            raise ValueError("policy_secret must contain at least 32 bytes")
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._secret = policy_secret
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
                CREATE TABLE IF NOT EXISTS emergency_cases (
                    case_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    state_version INTEGER NOT NULL,
                    device_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS emergency_inputs (
                    input_id TEXT PRIMARY KEY,
                    input_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _case(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "case_id": row["case_id"],
            "state": row["state"],
            "state_version": row["state_version"],
            "device_id": row["device_id"],
            "profile_id": row["profile_id"],
            "session_id": row["session_id"],
            "correlation_id": row["correlation_id"],
            "signal_type": row["signal_type"],
        }

    @staticmethod
    def _event(case: dict[str, Any], event_type: str, causation_id: str,
               severity: str, payload: dict[str, Any]) -> dict[str, Any]:
        return new_event(
            event_type=event_type,
            device_id=case["device_id"],
            profile_id=case["profile_id"],
            session_id=case["session_id"],
            correlation_id=case["correlation_id"],
            causation_id=causation_id,
            source="emergency.state_machine",
            severity=severity,
            privacy_class="emergency",
            retention_class="audit",
            payload=payload,
        )

    @staticmethod
    def _assert_trusted_source(source: str, allowed: frozenset[str]) -> None:
        if source in AGENT_SOURCES:
            raise EmergencyTransitionError("agent output is not an emergency authority")
        if source not in allowed:
            raise EmergencyTransitionError(f"untrusted emergency source: {source}")

    @staticmethod
    def _replay_or_conflict(connection: sqlite3.Connection, input_id: str,
                            request_hash: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT input_sha256, result_json FROM emergency_inputs WHERE input_id=?",
            (input_id,),
        ).fetchone()
        if row is None:
            return None
        if row["input_sha256"] != request_hash:
            raise EmergencyReplayConflict("input ID was reused with different content")
        result = json.loads(row["result_json"])
        result["replayed"] = True
        return result

    @staticmethod
    def _save_result(connection: sqlite3.Connection, input_id: str,
                     request_hash: str, result: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO emergency_inputs (input_id, input_sha256, result_json) VALUES (?, ?, ?)",
            (
                input_id,
                request_hash,
                json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )

    def start_case(
        self,
        *,
        signal_type: str,
        source_kind: str,
        source_event_id: str,
        device_id: str,
        profile_id: str,
        session_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if signal_type not in SIGNAL_TYPES:
            raise EmergencyTransitionError("unknown emergency signal type")
        self._assert_trusted_source(source_kind, SIGNAL_SOURCES)
        _uuid(source_event_id, "source_event_id")
        for field, value in (
            ("device_id", device_id), ("profile_id", profile_id),
            ("session_id", session_id), ("correlation_id", correlation_id),
        ):
            _id(value, field)
        request = {
            "operation": "start", "signal_type": signal_type, "source_kind": source_kind,
            "source_event_id": source_event_id, "device_id": device_id,
            "profile_id": profile_id, "session_id": session_id,
            "correlation_id": correlation_id,
        }
        request_hash = _canonical_hash(request)
        case_id = "emergency-" + str(uuid.uuid5(uuid.NAMESPACE_URL, source_event_id))
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._replay_or_conflict(connection, source_event_id, request_hash)
            if replay is not None:
                connection.commit()
                return replay
            connection.execute(
                "INSERT INTO emergency_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (case_id, "awaiting_confirmation", 1, device_id, profile_id, session_id,
                 correlation_id, signal_type, now, now),
            )
            case = {
                "case_id": case_id, "state": "awaiting_confirmation", "state_version": 1,
                "device_id": device_id, "profile_id": profile_id, "session_id": session_id,
                "correlation_id": correlation_id, "signal_type": signal_type,
            }
            event = self._event(
                case, "emergency.confirmation_requested", source_event_id, "critical",
                {"case_id": case_id, "state_version": 1, "signal_type": signal_type},
            )
            result = {"case": case, "event": event, "replayed": False}
            self._save_result(connection, source_event_id, request_hash, result)
            connection.commit()
            return result

    def respond(self, *, case_id: str, response: str, source_kind: str,
                source_event_id: str) -> dict[str, Any]:
        _id(case_id, "case_id")
        _uuid(source_event_id, "source_event_id")
        if response not in RESPONSES:
            raise EmergencyTransitionError("unknown emergency response")
        self._assert_trusted_source(source_kind, RESPONSE_SOURCES)
        if response == "timeout" and source_kind != "policy_timer":
            raise EmergencyTransitionError("only policy_timer may submit timeout")
        if response != "timeout" and source_kind == "policy_timer":
            raise EmergencyTransitionError("policy_timer cannot impersonate a person")
        request = {
            "operation": "respond", "case_id": case_id, "response": response,
            "source_kind": source_kind, "source_event_id": source_event_id,
        }
        request_hash = _canonical_hash(request)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._replay_or_conflict(connection, source_event_id, request_hash)
            if replay is not None:
                connection.commit()
                return replay
            row = connection.execute(
                "SELECT * FROM emergency_cases WHERE case_id=?", (case_id,)
            ).fetchone()
            if row is None:
                raise EmergencyTransitionError("emergency case not found")
            case = self._case(row)
            if case["state"] != "awaiting_confirmation":
                raise EmergencyTransitionError("case is not awaiting confirmation")
            new_version = case["state_version"] + 1
            if response == "safe":
                new_state = "resolved"
                event_type = "emergency.dismissed"
                severity = "notice"
            else:
                new_state = "ready_to_escalate"
                event_type = "emergency.ready"
                severity = "critical"
            connection.execute(
                "UPDATE emergency_cases SET state=?, state_version=?, updated_at=? WHERE case_id=?",
                (new_state, new_version, dt.datetime.now(dt.timezone.utc).isoformat(), case_id),
            )
            case.update(state=new_state, state_version=new_version)
            event = self._event(
                case, event_type, source_event_id, severity,
                {"case_id": case_id, "state_version": new_version, "response": response},
            )
            result = {"case": case, "event": event, "replayed": False}
            self._save_result(connection, source_event_id, request_hash, result)
            connection.commit()
            return result

    def authorize_escalation(self, authorization: dict[str, Any], *,
                             now: dt.datetime | None = None) -> dict[str, Any]:
        expected = {"authorization_id", "case_id", "state_version", "channel",
                    "expires_at", "signature"}
        if not isinstance(authorization, dict) or set(authorization) != expected:
            raise EmergencyTransitionError("authorization fields must exactly match contract")
        auth_id = _uuid(authorization["authorization_id"], "authorization_id")
        case_id = _id(authorization["case_id"], "case_id")
        version = authorization["state_version"]
        if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
            raise EmergencyTransitionError("state_version must be a positive integer")
        channel = authorization["channel"]
        if channel not in ESCALATION_CHANNELS:
            raise EmergencyTransitionError("escalation channel is disabled or unknown")
        expiry = _utc(authorization["expires_at"], "expires_at")
        current = now or dt.datetime.now(dt.timezone.utc)
        if current.tzinfo is None:
            raise EmergencyTransitionError("now must be timezone-aware")
        signature = authorization["signature"]
        if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise EmergencyTransitionError("authorization signature has invalid syntax")
        expected_signature = hmac.new(
            self._secret,
            _authorization_message(case_id, version, channel,
                                   authorization["expires_at"], auth_id),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise EmergencyTransitionError("authorization signature is invalid")
        request_hash = _canonical_hash(authorization)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._replay_or_conflict(connection, auth_id, request_hash)
            if replay is not None:
                connection.commit()
                return replay
            if not current <= expiry <= current + dt.timedelta(minutes=5):
                raise EmergencyTransitionError("authorization is expired or too long-lived")
            row = connection.execute(
                "SELECT * FROM emergency_cases WHERE case_id=?", (case_id,)
            ).fetchone()
            if row is None:
                raise EmergencyTransitionError("emergency case not found")
            case = self._case(row)
            if case["state"] != "ready_to_escalate":
                raise EmergencyTransitionError("case is not ready to escalate")
            if case["state_version"] != version:
                raise EmergencyTransitionError("authorization state version is stale")
            new_version = version + 1
            connection.execute(
                "UPDATE emergency_cases SET state='escalating', state_version=?, updated_at=? "
                "WHERE case_id=?",
                (new_version, dt.datetime.now(dt.timezone.utc).isoformat(), case_id),
            )
            case.update(state="escalating", state_version=new_version)
            event = self._event(
                case, "emergency.escalation_started", auth_id, "critical",
                {"case_id": case_id, "state_version": new_version, "channel": channel,
                 "automatic_emergency_services": False},
            )
            result = {"case": case, "event": event, "replayed": False}
            self._save_result(connection, auth_id, request_hash, result)
            connection.commit()
            return result

    def agent_advisory(self, *, case_id: str, text: str) -> dict[str, Any]:
        """Return status without persisting text or changing emergency state."""
        _id(case_id, "case_id")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM emergency_cases WHERE case_id=?", (case_id,)
            ).fetchone()
            if row is None:
                raise EmergencyTransitionError("emergency case not found")
            case = self._case(row)
        return {
            "case_id": case_id,
            "state": case["state"],
            "state_version": case["state_version"],
            "state_changed": False,
            "accepted_as_authority": False,
            "advisory_text_persisted": False,
        }
