#!/usr/bin/env python3
"""Deterministic pre-build regression matrix for safety-critical voice paths."""
from __future__ import annotations

import asyncio
import json
import struct
import unittest

import aihub_bridge_codex as bridge
from okja_event_contract import new_event
from okja_intent_confirmation import VoiceIntentSession


def transcript(text: str, *, correlation: str = "corr-a", profile: str = "personal") -> dict:
    return new_event(
        event_type="transcript.final",
        device_id="device-test",
        profile_id=f"profile-{profile}",
        session_id="session-test",
        correlation_id=correlation,
        source="android.voice",
        severity="info",
        privacy_class="sensitive",
        retention_class="volatile",
        payload={"profile": profile, "language": "ko-KR", "text": text},
    )


class ConfirmationIsolationTests(unittest.TestCase):
    def test_confirmation_is_correlation_local(self):
        session = VoiceIntentSession(confirmation_ttl_seconds=60)
        first = session.process(transcript("TV 켜줘", correlation="corr-old"), now_ms=1000)
        self.assertEqual("confirmation_requested", first["kind"])

        fresh = session.process(transcript("확인", correlation="corr-new"), now_ms=1500)
        self.assertEqual("assistant_query", fresh["kind"])
        self.assertFalse(any(e["event_type"] == "confirmation.accepted" for e in fresh["events"]))

    def test_expired_current_confirmation_cannot_execute(self):
        session = VoiceIntentSession(confirmation_ttl_seconds=5)
        session.process(transcript("에어컨 켜줘"), now_ms=1000)
        result = session.process(transcript("확인"), now_ms=7000)
        self.assertEqual("assistant_query", result["kind"])
        self.assertEqual("confirmation.rejected", result["events"][0]["event_type"])
        self.assertEqual("expired", result["events"][0]["payload"]["reason"])

    def test_abandoned_expired_correlations_are_pruned(self):
        session = VoiceIntentSession(confirmation_ttl_seconds=5)
        session.process(transcript("TV 켜줘", correlation="corr-old"), now_ms=1000)
        session.process(transcript("오늘 날씨 어때", correlation="corr-new"), now_ms=7000)
        self.assertNotIn(("device-test", "profile-personal", "session-test", "corr-old"), session._pending)


class DeviceNegationTests(unittest.TestCase):
    def test_korean_negated_on_command_is_not_device_intent(self):
        result = VoiceIntentSession().process(transcript("TV 켜지 마"), now_ms=1000)
        self.assertEqual("assistant_query", result["kind"])

    def test_korean_negated_off_command_is_not_device_intent(self):
        result = VoiceIntentSession().process(transcript("에어컨 끄지 마"), now_ms=1000)
        self.assertEqual("assistant_query", result["kind"])

    def test_english_negated_command_is_not_device_intent(self):
        event = transcript("don't turn on the TV")
        event["payload"]["language"] = "en-US"
        result = VoiceIntentSession().process(event, now_ms=1000)
        self.assertEqual("assistant_query", result["kind"])

    def test_positive_command_still_requires_confirmation(self):
        result = VoiceIntentSession().process(transcript("TV 켜줘"), now_ms=1000)
        self.assertEqual("confirmation_requested", result["kind"])
        self.assertEqual("tv", result["target"])
        self.assertEqual("power_on", result["action"])


class BridgeProtocolTests(unittest.TestCase):
    def test_transcript_length_limit(self):
        raw = json.dumps(transcript("x" * (bridge.MAX_TRANSCRIPT_CHARS + 1)))
        with self.assertRaisesRegex(ValueError, "maximum length"):
            bridge.parse_request(raw)

    def test_packet_declared_size_limit(self):
        async def scenario():
            reader = asyncio.StreamReader()
            reader.feed_data(struct.pack("!I", bridge.MAX_PACKET_BYTES + 1))
            reader.feed_eof()
            with self.assertRaisesRegex(ValueError, "invalid packet size"):
                await bridge.read_packet(reader)
        asyncio.run(scenario())

    def test_empty_packet_is_rejected(self):
        async def scenario():
            reader = asyncio.StreamReader()
            reader.feed_data(struct.pack("!I", 0))
            reader.feed_eof()
            with self.assertRaisesRegex(ValueError, "invalid packet size"):
                await bridge.read_packet(reader)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main(verbosity=2)
