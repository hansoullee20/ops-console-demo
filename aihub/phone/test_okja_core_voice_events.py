import unittest

from okja_core_voice_events import validate_core_voice_event
from okja_event_contract import new_event


def event(event_type, payload, privacy="household", cause=None):
    return new_event(
        event_type=event_type,
        device_id="device-1", profile_id="profile-personal",
        session_id="session-1", correlation_id="corr-1",
        causation_id=cause, source="android.voice", severity="info",
        privacy_class=privacy, retention_class="volatile", payload=payload,
    )


class CoreVoiceEventTests(unittest.TestCase):
    def test_wake_candidate_detected_and_rejected_are_exact(self):
        candidate = event("wake.candidate", {"language": "ko-KR", "candidate_count": 2})
        validate_core_voice_event(candidate)
        validate_core_voice_event(event("wake.detected", {"language": "ko-KR", "candidate_count": 2}, cause=candidate["event_id"]))
        validate_core_voice_event(event("wake.rejected", {"language": "ko-KR", "candidate_count": 2, "reason": "phrase_mismatch"}, cause=candidate["event_id"]))

    def test_listening_failure_and_transcript_failure_are_exact(self):
        started = event("listening.started", {"language": "en-US", "entrypoint": "button"})
        validate_core_voice_event(started)
        failed = event("listening.failed", {"language": "en-US", "error_code": 7}, cause=started["event_id"])
        validate_core_voice_event(failed)
        validate_core_voice_event(event("transcript.failed", {"language": "en-US", "error_code": 7}, cause=failed["event_id"]))

    def test_transcript_text_is_sensitive_and_exact(self):
        validate_core_voice_event(event("transcript.partial", {"language": "ko-KR", "text": "불 켜"}, privacy="sensitive"))
        validate_core_voice_event(event("transcript.final", {"profile": "personal", "language": "ko-KR", "text": "불 켜 줘"}, privacy="sensitive"))

    def test_unknown_payload_fields_and_wrong_privacy_fail_closed(self):
        bad = event("wake.candidate", {"language": "ko-KR", "candidate_count": 1, "text": "옥자"})
        with self.assertRaises(ValueError):
            validate_core_voice_event(bad)
        with self.assertRaises(ValueError):
            validate_core_voice_event(event("transcript.partial", {"language": "ko-KR", "text": "secret"}))


if __name__ == "__main__":
    unittest.main()
