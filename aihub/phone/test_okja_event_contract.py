import copy
import json
import unittest
from pathlib import Path

from okja_event_contract import (
    EVENT_TYPES,
    REQUIRED_FIELDS,
    assistant_failure,
    assistant_response,
    new_event,
    parse_assistant_result,
    parse_transcript_request,
    validate_event,
)


def transcript_event(**changes):
    event = new_event(
        event_type="transcript.final",
        device_id="device-123",
        profile_id="profile-grandma",
        session_id="session-123",
        correlation_id="corr-123",
        causation_id="listening-event-123",
        source="android.voice",
        privacy_class="sensitive",
        retention_class="volatile",
        payload={"profile": "grandma", "language": "ko-KR", "text": " 불 켜 줘 "},
        monotonic_ms=1234.5,
    )
    event.update(changes)
    return event


class OkjaEventContractTests(unittest.TestCase):
    def test_transcript_request_has_complete_versioned_envelope(self):
        event = transcript_event()
        parsed = parse_transcript_request(event)
        self.assertEqual(parsed["text"], "불 켜 줘")
        self.assertEqual(parsed["envelope"]["schema_version"], "okja.event.v1")
        self.assertEqual(parsed["envelope"]["retention_class"], "volatile")

    def test_response_preserves_identity_correlation_and_causation(self):
        request = transcript_event()
        response = assistant_response(request, "네, 확인할게요.")
        parse_assistant_result(response, request)
        self.assertEqual(response["device_id"], request["device_id"])
        self.assertEqual(response["profile_id"], request["profile_id"])
        self.assertEqual(response["session_id"], request["session_id"])
        self.assertEqual(response["correlation_id"], request["correlation_id"])
        self.assertEqual(response["causation_id"], request["event_id"])
        self.assertEqual(response["payload"], {"text": "네, 확인할게요."})

    def test_failure_is_structured_and_does_not_echo_transcript(self):
        request = transcript_event()
        failure = assistant_failure(request, "agent_timeout", "응답 시간 초과")
        self.assertEqual(failure["event_type"], "assistant.failed")
        self.assertEqual(failure["severity"], "error")
        self.assertNotIn(request["payload"]["text"], str(failure))
        parse_assistant_result(failure, request)

    def test_result_rejects_wrong_source_classification_payload_or_chain(self):
        request = transcript_event()
        valid = assistant_response(request, "확인")
        mutations = []
        for field, value in (
            ("source", "android.voice"),
            ("privacy_class", "public"),
            ("retention_class", "history_30d"),
            ("correlation_id", "different-correlation"),
            ("causation_id", "different-cause"),
        ):
            changed = copy.deepcopy(valid)
            changed[field] = value
            mutations.append(changed)
        extra_payload = copy.deepcopy(valid)
        extra_payload["payload"]["debug"] = "leak"
        mutations.append(extra_payload)
        for event in mutations:
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    parse_assistant_result(event, request)

    def test_unknown_missing_and_invalid_fields_fail_closed(self):
        cases = []
        missing = transcript_event()
        del missing["correlation_id"]
        cases.append(missing)
        extra = transcript_event(unexpected=True)
        cases.append(extra)
        cases.append(transcript_event(event_type="unknown.event"))
        cases.append(transcript_event(occurred_at="2026-08-13T08:00:00+09:00"))
        cases.append(transcript_event(monotonic_ms=float("nan")))
        for event in cases:
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    validate_event(event)

    def test_transcript_privacy_retention_and_profile_are_enforced(self):
        public = transcript_event(privacy_class="public")
        retained = transcript_event(retention_class="history_30d")
        wrong_profile = transcript_event(profile_id="profile-personal")
        extra_payload = transcript_event()
        extra_payload["payload"]["confidence"] = 0.9
        for event in (public, retained, wrong_profile, extra_payload):
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    parse_transcript_request(event)

    def test_event_id_must_be_uuid_and_causation_can_be_null(self):
        event = transcript_event(causation_id=None)
        validate_event(event)
        broken = copy.deepcopy(event)
        broken["event_id"] = "not-a-uuid"
        with self.assertRaisesRegex(ValueError, "UUID"):
            validate_event(broken)

    def test_json_schema_registry_matches_runtime_validator(self):
        schema = json.loads(
            Path(__file__).with_name("okja_event_v1.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), REQUIRED_FIELDS)
        self.assertEqual(set(schema["properties"]["event_type"]["enum"]), EVENT_TYPES)
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
