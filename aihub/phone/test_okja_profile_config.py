import copy
import datetime as dt
import json
import unittest
from pathlib import Path

from okja_profile_config import (
    ACCESSIBILITY_FIELDS,
    CAPABILITY_FIELDS,
    CONSENT_FIELDS,
    NOTIFICATION_EVENT_FIELDS,
    PROFILE_FIELDS,
    create_profile,
    validate_profile,
)


NOW = dt.datetime(2026, 8, 13, 8, 0, tzinfo=dt.timezone.utc)
CONSENT_TIME = "2026-08-13T08:01:00Z"


def decided(status="granted"):
    return {
        "status": status,
        "policy_version": "policy-v1",
        "updated_at": CONSENT_TIME,
    }


class ProfileConfigTests(unittest.TestCase):
    def senior(self):
        return create_profile(
            profile_id="profile-grandma",
            mode="senior",
            display_name="할머니",
            now=NOW,
        )

    def personal(self):
        return create_profile(
            profile_id="profile-personal",
            mode="personal",
            display_name="Han",
            locale="en-US",
            now=NOW,
        )

    def test_one_schema_validates_senior_and_personal_defaults(self):
        senior = self.senior()
        personal = self.personal()
        self.assertEqual(set(senior), set(personal))
        self.assertEqual(senior["schema_version"], "okja.profile.v1")
        self.assertEqual(senior["mode"], "senior")
        self.assertEqual(personal["mode"], "personal")
        self.assertGreaterEqual(senior["accessibility"]["minimum_touch_target_dp"], 64)
        self.assertEqual(senior["accessibility"]["calendar_display"], "both")
        self.assertTrue(senior["accessibility"]["night_mode"]["local_wake_available"])
        validate_profile(senior)
        validate_profile(personal)

    def test_senior_accessibility_minimums_fail_closed(self):
        profile = self.senior()
        invalid = []
        small_text = copy.deepcopy(profile)
        small_text["accessibility"]["text_scale"] = "standard"
        invalid.append(small_text)
        small_target = copy.deepcopy(profile)
        small_target["accessibility"]["minimum_touch_target_dp"] = 48
        invalid.append(small_target)
        no_night = copy.deepcopy(profile)
        no_night["accessibility"]["night_mode"]["enabled"] = False
        invalid.append(no_night)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_profile(candidate)

    def test_five_consents_are_exact_and_independent(self):
        profile = self.personal()
        profile["consents"]["essential_product"] = decided("granted")
        profile["consents"]["health_journal"] = decided("granted")
        profile["consents"]["caregiver_sharing"] = decided("declined")
        profile["consents"]["camera"] = decided("declined")
        profile["consents"]["benchmark_research"] = decided("granted")
        validate_profile(profile)
        self.assertEqual(set(profile["consents"]), CONSENT_FIELDS)
        self.assertEqual(profile["consents"]["camera"]["status"], "declined")
        self.assertEqual(profile["consents"]["benchmark_research"]["status"], "granted")

    def test_unset_and_decided_consent_records_have_distinct_requirements(self):
        profile = self.personal()
        invalid_unset = copy.deepcopy(profile)
        invalid_unset["consents"]["camera"]["policy_version"] = "policy-v1"
        invalid_decided = copy.deepcopy(profile)
        invalid_decided["consents"]["camera"] = {
            "status": "granted", "policy_version": "", "updated_at": None
        }
        for candidate in (invalid_unset, invalid_decided):
            with self.assertRaises(ValueError):
                validate_profile(candidate)

    def test_caregiver_notifications_require_recipient_and_sharing_consent(self):
        profile = self.senior()
        notifications = profile["caregiver_notifications"]
        notifications["enabled"] = True
        notifications["recipients"] = [
            {"caregiver_id": "caregiver-daughter", "channels": ["push", "call"]}
        ]
        notifications["events"]["arrival_departure"] = True
        with self.assertRaisesRegex(ValueError, "caregiver-sharing consent"):
            validate_profile(profile)
        profile["consents"]["caregiver_sharing"] = decided()
        validate_profile(profile)

    def test_health_notifications_also_require_health_consent(self):
        profile = self.senior()
        profile["consents"]["caregiver_sharing"] = decided()
        notifications = profile["caregiver_notifications"]
        notifications["enabled"] = True
        notifications["recipients"] = [
            {"caregiver_id": "caregiver-daughter", "channels": ["push"]}
        ]
        notifications["events"]["symptom_journal"] = True
        with self.assertRaisesRegex(ValueError, "health-journal consent"):
            validate_profile(profile)
        profile["consents"]["health_journal"] = decided()
        validate_profile(profile)

    def test_emergency_quiet_hours_override_is_narrow(self):
        profile = self.senior()
        profile["consents"]["caregiver_sharing"] = decided()
        notifications = profile["caregiver_notifications"]
        notifications["enabled"] = True
        notifications["recipients"] = [
            {"caregiver_id": "caregiver-daughter", "channels": ["push"]}
        ]
        notifications["quiet_hours_respected"] = False
        with self.assertRaises(ValueError):
            validate_profile(profile)
        notifications["events"]["emergency"] = True
        notifications["emergency_overrides_quiet_hours"] = True
        validate_profile(profile)

    def test_washer_stays_false_and_quick_actions_follow_capabilities(self):
        washer = self.senior()
        washer["device_capabilities"]["washer"] = True
        with self.assertRaisesRegex(ValueError, "washer"):
            validate_profile(washer)
        hidden_tv = self.senior()
        hidden_tv["device_capabilities"]["tv"] = False
        with self.assertRaisesRegex(ValueError, "quick action tv"):
            validate_profile(hidden_tv)

    def test_unknown_fields_duplicate_recipients_and_invalid_timezone_fail(self):
        unknown = self.personal()
        unknown["consents"]["bundled_all"] = decided()
        timezone = self.personal()
        timezone["timezone"] = "Mars/Olympus"
        duplicate = self.senior()
        duplicate["consents"]["caregiver_sharing"] = decided()
        duplicate["caregiver_notifications"].update(
            enabled=True,
            recipients=[
                {"caregiver_id": "caregiver-1", "channels": ["push"]},
                {"caregiver_id": "caregiver-1", "channels": ["sms"]},
            ],
        )
        for candidate in (unknown, timezone, duplicate):
            with self.assertRaises(ValueError):
                validate_profile(candidate)

    def test_schema_registry_matches_runtime_field_contracts(self):
        schema = json.loads(
            Path(__file__).with_name("okja_profile_v1.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), PROFILE_FIELDS)
        self.assertEqual(
            set(schema["properties"]["accessibility"]["required"]),
            ACCESSIBILITY_FIELDS,
        )
        self.assertEqual(
            set(schema["properties"]["device_capabilities"]["required"]),
            CAPABILITY_FIELDS,
        )
        self.assertEqual(
            set(schema["properties"]["caregiver_notifications"]["properties"]["events"]["required"]),
            NOTIFICATION_EVENT_FIELDS,
        )
        self.assertEqual(
            set(schema["properties"]["consents"]["required"]), CONSENT_FIELDS
        )
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
