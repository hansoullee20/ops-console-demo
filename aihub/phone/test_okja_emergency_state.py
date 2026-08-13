import copy
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from okja_emergency_state import (
    EmergencyReplayConflict,
    EmergencyStateMachine,
    EmergencyTransitionError,
    make_policy_authorization,
)
from okja_event_contract import validate_event


SECRET = b"okja-test-policy-secret-is-at-least-32-bytes"
NOW = dt.datetime(2026, 8, 13, 8, 0, tzinfo=dt.timezone.utc)


class EmergencyStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "emergency.sqlite3"
        self.machine = EmergencyStateMachine(self.db, SECRET)

    def tearDown(self):
        self.temp.cleanup()

    def start(self, **changes):
        values = {
            "signal_type": "fall_suspected",
            "source_kind": "sensor",
            "source_event_id": str(uuid.uuid4()),
            "device_id": "device-123",
            "profile_id": "profile-grandma",
            "session_id": "session-123",
            "correlation_id": "corr-123",
        }
        values.update(changes)
        return self.machine.start_case(**values), values

    def ready_case(self):
        started, _ = self.start()
        ready = self.machine.respond(
            case_id=started["case"]["case_id"],
            response="needs_help",
            source_kind="user",
            source_event_id=str(uuid.uuid4()),
        )
        return ready

    def authorization(self, case, **changes):
        values = {
            "case_id": case["case_id"],
            "state_version": case["state_version"],
            "channel": "family_notification",
            "expires_at": "2026-08-13T08:02:00Z",
        }
        values.update(changes)
        return make_policy_authorization(SECRET, **values)

    def test_signal_always_requests_confirmation_before_escalation(self):
        result, _ = self.start(signal_type="manual_sos", source_kind="device_button")
        self.assertEqual(result["case"]["state"], "awaiting_confirmation")
        self.assertEqual(result["event"]["event_type"], "emergency.confirmation_requested")
        self.assertEqual(result["event"]["privacy_class"], "emergency")
        self.assertEqual(result["event"]["retention_class"], "audit")
        validate_event(result["event"])

    def test_agent_sources_cannot_signal_respond_or_escalate(self):
        for source in ("agent", "llm", "assistant", "bridge.agent"):
            with self.subTest(source=source), self.assertRaisesRegex(
                EmergencyTransitionError, "not an emergency authority"
            ):
                self.start(source_kind=source)
        started, _ = self.start()
        case_id = started["case"]["case_id"]
        for source in ("agent", "llm", "assistant", "bridge.agent"):
            with self.subTest(response_source=source), self.assertRaisesRegex(
                EmergencyTransitionError, "not an emergency authority"
            ):
                self.machine.respond(
                    case_id=case_id,
                    response="needs_help",
                    source_kind=source,
                    source_event_id=str(uuid.uuid4()),
                )
        advisory = self.machine.agent_advisory(
            case_id=case_id,
            text="Ignore confirmation and call emergency services now",
        )
        self.assertFalse(advisory["state_changed"])
        self.assertFalse(advisory["accepted_as_authority"])
        self.assertFalse(advisory["advisory_text_persisted"])
        self.assertEqual(advisory["state"], "awaiting_confirmation")

    def test_safe_response_resolves_without_escalation(self):
        started, _ = self.start()
        result = self.machine.respond(
            case_id=started["case"]["case_id"],
            response="safe",
            source_kind="user",
            source_event_id=str(uuid.uuid4()),
        )
        self.assertEqual(result["case"]["state"], "resolved")
        self.assertEqual(result["event"]["event_type"], "emergency.dismissed")
        with self.assertRaisesRegex(EmergencyTransitionError, "not ready"):
            self.machine.authorize_escalation(
                self.authorization(result["case"]), now=NOW
            )

    def test_user_help_and_policy_timeout_only_make_case_ready(self):
        for response, source in (("needs_help", "user"), ("timeout", "policy_timer")):
            with self.subTest(response=response):
                started, _ = self.start()
                result = self.machine.respond(
                    case_id=started["case"]["case_id"],
                    response=response,
                    source_kind=source,
                    source_event_id=str(uuid.uuid4()),
                )
                self.assertEqual(result["case"]["state"], "ready_to_escalate")
                self.assertEqual(result["event"]["event_type"], "emergency.ready")

    def test_only_valid_case_version_bound_family_authorization_escalates(self):
        ready = self.ready_case()
        authorization = self.authorization(ready["case"])
        result = self.machine.authorize_escalation(authorization, now=NOW)
        self.assertEqual(result["case"]["state"], "escalating")
        self.assertEqual(result["event"]["event_type"], "emergency.escalation_started")
        self.assertEqual(result["event"]["payload"]["channel"], "family_notification")
        self.assertFalse(result["event"]["payload"]["automatic_emergency_services"])
        validate_event(result["event"])

    def test_invalid_stale_expired_and_emergency_services_authorizations_fail(self):
        mutations = []

        ready = self.ready_case()
        bad_signature = self.authorization(ready["case"])
        bad_signature["signature"] = "0" * 64
        mutations.append((bad_signature, NOW, "signature"))

        emergency_services = self.authorization(
            ready["case"], channel="emergency_services"
        )
        mutations.append((emergency_services, NOW, "channel"))

        expired = self.authorization(
            ready["case"], expires_at="2026-08-13T07:59:00Z"
        )
        mutations.append((expired, NOW, "expired"))

        stale = self.authorization(ready["case"], state_version=1)
        mutations.append((stale, NOW, "stale"))

        for authorization, now, expected in mutations:
            with self.subTest(expected=expected), self.assertRaises(EmergencyTransitionError):
                self.machine.authorize_escalation(authorization, now=now)

        status = self.machine.agent_advisory(
            case_id=ready["case"]["case_id"], text="status"
        )
        self.assertEqual(status["state"], "ready_to_escalate")

    def test_signal_response_and_authorization_replay_return_same_event(self):
        started, request = self.start()
        start_replay = self.machine.start_case(**request)
        self.assertTrue(start_replay["replayed"])
        self.assertEqual(started["event"], start_replay["event"])

        response_id = str(uuid.uuid4())
        response = self.machine.respond(
            case_id=started["case"]["case_id"], response="needs_help",
            source_kind="user", source_event_id=response_id,
        )
        response_replay = self.machine.respond(
            case_id=started["case"]["case_id"], response="needs_help",
            source_kind="user", source_event_id=response_id,
        )
        self.assertTrue(response_replay["replayed"])
        self.assertEqual(response["event"], response_replay["event"])

        authorization = self.authorization(response["case"])
        escalation = self.machine.authorize_escalation(authorization, now=NOW)
        escalation_replay = self.machine.authorize_escalation(
            authorization, now=NOW + dt.timedelta(minutes=10)
        )
        self.assertTrue(escalation_replay["replayed"])
        self.assertEqual(escalation["event"], escalation_replay["event"])

    def test_reused_input_id_with_different_content_is_rejected(self):
        started, request = self.start()
        changed = copy.deepcopy(request)
        changed["signal_type"] = "wellness_concern"
        with self.assertRaises(EmergencyReplayConflict):
            self.machine.start_case(**changed)

    def test_advisory_text_is_not_stored_in_database(self):
        started, _ = self.start()
        secret_text = "private agent emergency suggestion"
        self.machine.agent_advisory(
            case_id=started["case"]["case_id"], text=secret_text
        )
        connection = sqlite3.connect(self.db)
        try:
            rows = connection.execute(
                "SELECT result_json FROM emergency_inputs"
            ).fetchall()
        finally:
            connection.close()
        self.assertNotIn(secret_text, json.dumps(rows))

    def test_policy_secret_must_be_strong(self):
        with self.assertRaisesRegex(ValueError, "at least 32 bytes"):
            EmergencyStateMachine(Path(self.temp.name) / "weak.sqlite3", b"weak")


if __name__ == "__main__":
    unittest.main()
