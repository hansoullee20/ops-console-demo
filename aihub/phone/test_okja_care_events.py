import copy
import datetime as dt
import unittest
import uuid

from okja_care_events import new_care_event, validate_care_event
from okja_profile_config import create_profile


NOW = dt.datetime(2026, 8, 13, 8, 0, tzinfo=dt.timezone.utc)
EVENT_ID = str(uuid.uuid4())


def granted():
    return {
        "status": "granted",
        "policy_version": "policy-v1",
        "updated_at": "2026-08-13T08:00:00Z",
    }


class CareEventTests(unittest.TestCase):
    def profile(self, *, health=True, sharing=True, notifications=True):
        profile = create_profile(
            profile_id="profile-grandma",
            mode="senior",
            display_name="할머니",
            now=NOW,
        )
        if health:
            profile["consents"]["health_journal"] = granted()
        if sharing:
            profile["consents"]["caregiver_sharing"] = granted()
        if notifications:
            prefs = profile["caregiver_notifications"]
            prefs["enabled"] = True
            prefs["recipients"] = [
                {"caregiver_id": "caregiver-daughter", "channels": ["push", "call"]}
            ]
            prefs["events"].update(
                wellness=True,
                symptom_journal=True,
                arrival_departure=True,
                inactivity=True,
                emergency=True,
                family_eta=True,
            )
            prefs["emergency_overrides_quiet_hours"] = True
        return profile

    def event(self, event_type, payload, *, profile=None, source="care.ui"):
        return new_care_event(
            event_type=event_type,
            profile=profile or self.profile(),
            device_id="device-123",
            session_id="session-123",
            correlation_id="corr-123",
            causation_id=EVENT_ID,
            source=source,
            payload=payload,
        )

    def test_wellness_prompt_requires_snooze_decline_and_health_consent(self):
        payload = {
            "prompt_id": "wellness-morning",
            "scheduled_for": "2026-08-13T08:00:00Z",
            "can_snooze": True,
            "can_decline": True,
        }
        event = self.event("wellness.checkin_requested", payload, source="care.scheduler")
        self.assertEqual(event["privacy_class"], "personal")
        self.assertEqual(event["retention_class"], "history_30d")
        no_consent = self.profile(health=False)
        with self.assertRaisesRegex(ValueError, "health-journal consent"):
            self.event(
                "wellness.checkin_requested", payload,
                profile=no_consent, source="care.scheduler",
            )
        blocked = copy.deepcopy(payload)
        blocked["can_decline"] = False
        with self.assertRaisesRegex(ValueError, "snooze and decline"):
            self.event("wellness.checkin_requested", blocked, source="care.scheduler")

    def test_wellness_record_accepts_snoozed_and_declined(self):
        for response in ("snoozed", "declined"):
            event = self.event(
                "wellness.checkin_recorded",
                {"prompt_id": "wellness-morning", "response": response, "note": None},
            )
            self.assertEqual(event["payload"]["response"], response)
            self.assertEqual(event["privacy_class"], "health")

    def test_symptom_is_self_reported_record_not_diagnosis(self):
        payload = {
            "record_id": str(uuid.uuid4()),
            "reported_text": "아침부터 무릎이 아파요",
            "body_area": "knee",
            "self_reported_severity": "moderate",
            "sharing_requested": False,
        }
        event = self.event("symptom.recorded", payload)
        self.assertEqual(set(event["payload"]), set(payload))
        self.assertNotIn("diagnosis", event["payload"])
        diagnosed = copy.deepcopy(payload)
        diagnosed["diagnosis"] = "arthritis"
        with self.assertRaises(ValueError):
            self.event("symptom.recorded", diagnosed)

    def test_symptom_sharing_requires_separate_caregiver_consent(self):
        profile = self.profile(sharing=False, notifications=False)
        payload = {
            "record_id": str(uuid.uuid4()),
            "reported_text": "머리가 아파요",
            "body_area": "head",
            "self_reported_severity": "mild",
            "sharing_requested": True,
        }
        with self.assertRaisesRegex(ValueError, "caregiver-sharing consent"):
            self.event("symptom.recorded", payload, profile=profile)

    def test_presence_events_are_explicitly_estimated_confirmed_or_corrected(self):
        payload = {
            "person_profile_id": "profile-grandma",
            "home_id": "home-grandma",
            "observed_at": "2026-08-13T08:00:00Z",
            "estimate_status": "estimated",
            "confidence": 0.8,
            "evidence_sources": ["door_sensor", "presence_sensor"],
        }
        arrived = self.event("presence.arrived", payload, source="sensor.fusion")
        departed = self.event("presence.departed", payload, source="sensor.fusion")
        self.assertEqual(arrived["payload"]["estimate_status"], "estimated")
        self.assertEqual(departed["payload"]["estimate_status"], "estimated")
        self.assertNotEqual(arrived["event_id"], departed["event_id"])

    def test_family_eta_requires_sharing_consent_and_sender_identity(self):
        payload = {
            "sender_profile_id": "profile-grandma",
            "recipient_profile_id": "profile-personal",
            "eta_minutes": 20,
            "status": "on_the_way",
            "message": "곧 도착해요",
        }
        event = self.event("family.eta_updated", payload, source="family.app")
        self.assertEqual(event["privacy_class"], "household")
        with self.assertRaisesRegex(ValueError, "caregiver-sharing consent"):
            self.event(
                "family.eta_updated", payload,
                profile=self.profile(sharing=False, notifications=False),
                source="family.app",
            )

    def test_notification_request_must_match_preferences_recipients_and_summary(self):
        payload = {
            "notification_id": str(uuid.uuid4()),
            "subject_event_id": EVENT_ID,
            "category": "symptom_journal",
            "deliveries": [
                {"caregiver_id": "caregiver-daughter", "channel": "push"}
            ],
            "summary_code": "symptom_shared",
        }
        event = self.event(
            "notification.requested", payload, source="care.notification_policy"
        )
        self.assertEqual(event["retention_class"], "audit")
        wrong_summary = copy.deepcopy(payload)
        wrong_summary["summary_code"] = "emergency"
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.event(
                "notification.requested", wrong_summary,
                source="care.notification_policy",
            )
        wrong_recipient = copy.deepcopy(payload)
        wrong_recipient["deliveries"][0]["caregiver_id"] = "caregiver-unknown"
        with self.assertRaisesRegex(ValueError, "not configured"):
            self.event(
                "notification.requested", wrong_recipient,
                source="care.notification_policy",
            )
        wrong_subject = copy.deepcopy(payload)
        wrong_subject["subject_event_id"] = str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError, "must match causation_id"):
            self.event(
                "notification.requested", wrong_subject,
                source="care.notification_policy",
            )

    def test_emergency_notification_is_critical_but_not_119_action(self):
        payload = {
            "notification_id": str(uuid.uuid4()),
            "subject_event_id": EVENT_ID,
            "category": "emergency",
            "deliveries": [
                {"caregiver_id": "caregiver-daughter", "channel": "call"}
            ],
            "summary_code": "emergency",
        }
        event = self.event(
            "notification.requested", payload, source="care.notification_policy"
        )
        self.assertEqual(event["severity"], "critical")
        self.assertEqual(event["privacy_class"], "emergency")
        self.assertNotIn("emergency_services", str(event))

    def test_notification_delivery_and_failure_are_typed_audit_events(self):
        notification_id = str(uuid.uuid4())
        delivered = self.event(
            "notification.delivered",
            {
                "notification_id": notification_id,
                "caregiver_id": "caregiver-daughter",
                "channel": "push",
                "attempt": 1,
                "delivered_at": "2026-08-13T08:01:00Z",
            },
            source="notification.dispatcher",
        )
        failed = self.event(
            "notification.failed",
            {
                "notification_id": notification_id,
                "caregiver_id": "caregiver-daughter",
                "channel": "call",
                "attempt": 1,
                "error_code": "provider_unavailable",
                "retryable": True,
            },
            source="notification.dispatcher",
        )
        self.assertEqual(delivered["event_type"], "notification.delivered")
        self.assertEqual(failed["severity"], "warning")

    def test_agent_sources_and_policy_tampering_fail(self):
        payload = {
            "record_id": str(uuid.uuid4()),
            "reported_text": "배가 아파요",
            "body_area": "abdomen",
            "self_reported_severity": "mild",
            "sharing_requested": False,
        }
        with self.assertRaisesRegex(ValueError, "source"):
            self.event("symptom.recorded", payload, source="bridge.agent")
        event = self.event("symptom.recorded", payload)
        tampered = copy.deepcopy(event)
        tampered["privacy_class"] = "public"
        with self.assertRaisesRegex(ValueError, "policy mismatch"):
            validate_care_event(tampered, self.profile())


if __name__ == "__main__":
    unittest.main()
