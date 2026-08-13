import unittest

from okja_event_contract import new_event
from okja_intent_confirmation import VoiceIntentSession, validate_intent_confirmation_event


def transcript(text="오늘 날씨 알려줘", *, language="ko-KR", event_id=None):
    return new_event(
        event_type="transcript.final",
        device_id="device-1",
        profile_id="profile-personal",
        session_id="session-1",
        correlation_id="corr-1",
        causation_id=None,
        source="android.voice",
        severity="info",
        privacy_class="sensitive",
        retention_class="volatile",
        payload={"profile": "personal", "language": language, "text": text},
        event_id=event_id,
    )


class IntentConfirmationTests(unittest.TestCase):
    def test_ordinary_query_is_structured_without_copying_transcript(self):
        session = VoiceIntentSession()
        result = session.process(transcript("오늘 날씨 알려줘"), now_ms=1000)
        self.assertEqual("assistant_query", result["kind"])
        self.assertEqual(["intent.requested", "intent.resolved"], [e["event_type"] for e in result["events"]])
        resolved = result["events"][-1]
        self.assertEqual("assistant.query", resolved["payload"]["intent_kind"])
        self.assertFalse(resolved["payload"]["requires_confirmation"])
        self.assertNotIn("오늘", str(resolved["payload"]))
        for event in result["events"]:
            validate_intent_confirmation_event(event)

    def test_device_intent_requests_confirmation_and_does_not_execute(self):
        session = VoiceIntentSession(confirmation_ttl_seconds=60)
        result = session.process(transcript("티비 켜줘"), now_ms=1000)
        self.assertEqual("confirmation_requested", result["kind"])
        self.assertEqual(("tv", "power_on"), (result["target"], result["action"]))
        self.assertEqual(
            ["intent.requested", "intent.resolved", "confirmation.requested"],
            [e["event_type"] for e in result["events"]],
        )
        self.assertEqual(60, result["events"][-1]["payload"]["expires_in_seconds"])

    def test_explicit_confirm_emits_acceptance_caused_by_original_request(self):
        session = VoiceIntentSession()
        first = session.process(transcript("에어컨 꺼줘"), now_ms=1000)
        confirmation_id = first["events"][-1]["event_id"]
        second = session.process(transcript("확인"), now_ms=2000)
        self.assertEqual("confirmation_accepted", second["kind"])
        self.assertEqual(["intent.requested", "intent.resolved", "confirmation.accepted"], [e["event_type"] for e in second["events"]])
        self.assertEqual(confirmation_id, second["events"][-1]["causation_id"])
        third = session.process(transcript("확인"), now_ms=3000)
        self.assertEqual("assistant_query", third["kind"])

    def test_explicit_cancel_emits_rejection(self):
        session = VoiceIntentSession()
        session.process(transcript("휴대폰 찾아줘"), now_ms=1000)
        second = session.process(transcript("취소"), now_ms=2000)
        self.assertEqual("confirmation_rejected", second["kind"])
        self.assertEqual("explicit_cancel", second["events"][-1]["payload"]["reason"])

    def test_unrecognized_confirmation_keeps_pending(self):
        session = VoiceIntentSession()
        session.process(transcript("티비 꺼줘"), now_ms=1000)
        retry = session.process(transcript("뭐라고?"), now_ms=2000)
        self.assertEqual("confirmation_retry", retry["kind"])
        self.assertEqual("intent.failed", retry["events"][-1]["event_type"])
        accepted = session.process(transcript("확인"), now_ms=3000)
        self.assertEqual("confirmation_accepted", accepted["kind"])

    def test_expired_confirmation_is_rejected_before_new_intent(self):
        session = VoiceIntentSession(confirmation_ttl_seconds=5)
        first = session.process(transcript("티비 켜줘"), now_ms=1000)
        confirmation_id = first["events"][-1]["event_id"]
        result = session.process(transcript("오늘 일정 알려줘"), now_ms=7001)
        self.assertEqual("assistant_query", result["kind"])
        self.assertEqual("confirmation.rejected", result["events"][0]["event_type"])
        self.assertEqual("expired", result["events"][0]["payload"]["reason"])
        self.assertEqual(confirmation_id, result["events"][0]["causation_id"])

    def test_validator_fails_closed_on_extra_payload(self):
        session = VoiceIntentSession()
        event = session.process(transcript("hello", language="en-US"), now_ms=1000)["events"][0]
        event["payload"]["text"] = "hello"
        with self.assertRaises(ValueError):
            validate_intent_confirmation_event(event)


if __name__ == "__main__":
    unittest.main()
