import copy
import datetime as dt
import json
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from okja_device_command import (
    CAPABILITIES,
    COMMAND_FIELDS,
    DeviceCommandService,
    IdempotencyConflict,
    capability_manifest,
    validate_command,
)
from okja_event_contract import validate_event


NOW = dt.datetime(2026, 8, 13, 8, 0, tzinfo=dt.timezone.utc)


def command(target="tv", action="power_on", parameters=None, **changes):
    row = {
        "schema_version": "okja.device-command.v1",
        "command_id": str(uuid.uuid4()),
        "idempotency_key": "idem-test-1",
        "issued_at": "2026-08-13T07:59:00Z",
        "expires_at": "2026-08-13T08:02:00Z",
        "device_id": "device-123",
        "profile_id": "profile-grandma",
        "session_id": "session-123",
        "correlation_id": "corr-123",
        "source_event_id": str(uuid.uuid4()),
        "target": target,
        "action": action,
        "parameters": {} if parameters is None else parameters,
    }
    row.update(changes)
    return row


class DeviceCommandTests(unittest.TestCase):
    def service(self, root: str, adapters=None):
        return DeviceCommandService(Path(root) / "idempotency.sqlite3", adapters)

    def test_capability_manifest_has_three_enabled_and_disabled_washer(self):
        manifest = capability_manifest()
        self.assertTrue(manifest["capabilities"]["tv"]["enabled"])
        self.assertTrue(manifest["capabilities"]["ac"]["enabled"])
        self.assertTrue(manifest["capabilities"]["phone_finder"]["enabled"])
        self.assertFalse(manifest["capabilities"]["washer"]["enabled"])
        self.assertEqual(
            manifest["capabilities"]["washer"]["disabled_reason"],
            "reserved_until_physical_integration_exists",
        )

    def test_success_is_executed_once_and_replayed_with_same_events(self):
        calls = []

        def adapter(request):
            calls.append(request["command_id"])
            return {"confirmed": True}

        with tempfile.TemporaryDirectory() as temp:
            service = self.service(temp, {"tv": adapter})
            request = command()
            first = service.execute(request, now=NOW)
            replay = service.execute(copy.deepcopy(request), now=NOW)
        self.assertEqual(len(calls), 1)
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["accepted_event"], replay["accepted_event"])
        self.assertEqual(first["terminal_event"], replay["terminal_event"])
        validate_event(first["accepted_event"])
        validate_event(first["terminal_event"])
        self.assertEqual(first["accepted_event"]["event_type"], "command.accepted")
        self.assertEqual(first["terminal_event"]["event_type"], "command.completed")
        self.assertEqual(
            first["terminal_event"]["causation_id"], first["accepted_event"]["event_id"]
        )

    def test_reused_key_with_different_request_fails_without_execution(self):
        calls = []

        def adapter(request):
            calls.append(request["action"])
            return {}

        with tempfile.TemporaryDirectory() as temp:
            service = self.service(temp, {"tv": adapter})
            original = command()
            service.execute(original, now=NOW)
            changed = copy.deepcopy(original)
            changed["action"] = "power_off"
            with self.assertRaises(IdempotencyConflict):
                service.execute(changed, now=NOW)
        self.assertEqual(calls, ["power_on"])

    def test_concurrent_duplicate_never_runs_adapter_twice(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def adapter(request):
            calls.append(request["command_id"])
            entered.set()
            self.assertTrue(release.wait(2))
            return {"confirmed": True}

        with tempfile.TemporaryDirectory() as temp:
            service = self.service(temp, {"tv": adapter})
            request = command()
            holder = {}
            thread = threading.Thread(
                target=lambda: holder.setdefault("first", service.execute(request, now=NOW))
            )
            thread.start()
            self.assertTrue(entered.wait(2))
            duplicate = service.execute(copy.deepcopy(request), now=NOW)
            release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(calls), 1)
        self.assertEqual(duplicate["state"], "in_progress")
        self.assertTrue(duplicate["replayed"])
        self.assertEqual(holder["first"]["state"], "complete")

    def test_disabled_washer_is_durable_failure_and_never_calls_adapter(self):
        calls = []
        request = command("washer", "start", idempotency_key="washer-1")
        with tempfile.TemporaryDirectory() as temp:
            service = self.service(temp, {"washer": lambda row: calls.append(row)})
            first = service.execute(request, now=NOW)
            replay = service.execute(request, now=NOW)
        self.assertEqual(calls, [])
        self.assertIsNone(first["accepted_event"])
        self.assertEqual(first["terminal_event"]["event_type"], "command.failed")
        self.assertEqual(
            first["terminal_event"]["payload"]["error_code"], "capability_disabled"
        )
        self.assertTrue(replay["replayed"])

    def test_missing_adapter_and_adapter_failure_are_cached_failures(self):
        cases = [
            ({}, "adapter_unavailable"),
            ({"ac": lambda request: (_ for _ in ()).throw(RuntimeError("secret"))}, "adapter_failed"),
        ]
        for index, (adapters, error_code) in enumerate(cases):
            with self.subTest(error_code=error_code), tempfile.TemporaryDirectory() as temp:
                request = command(
                    "ac", "power_on", idempotency_key=f"failure-{index}"
                )
                service = self.service(temp, adapters)
                result = service.execute(request, now=NOW)
                replay = service.execute(request, now=NOW)
                self.assertEqual(result["terminal_event"]["payload"]["error_code"], error_code)
                self.assertNotIn("secret", json.dumps(result))
                self.assertTrue(replay["replayed"])

    def test_target_action_parameters_and_expiry_fail_closed(self):
        invalid = [
            command("tv", "set_temperature", {"celsius": 22}),
            command("tv", "volume_up", {"steps": 0}),
            command("tv", "set_channel", {"channel": ""}),
            command("ac", "set_temperature", {"celsius": 31}),
            command("ac", "set_mode", {"mode": "heat"}),
            command("phone_finder", "ring", {"duration_seconds": 121}),
            command(expires_at="2026-08-13T07:59:30Z"),
            command(
                issued_at="2026-08-13T08:01:00Z",
                expires_at="2026-08-13T08:03:00Z",
            ),
            command(unexpected=True),
        ]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                validate_command(request, now=NOW)

    def test_schema_and_runtime_registry_are_in_sync(self):
        schema = json.loads(
            Path(__file__).with_name("okja_device_command_v1.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), COMMAND_FIELDS)
        self.assertEqual(set(schema["properties"]["target"]["enum"]), set(CAPABILITIES))
        runtime_actions = {
            action for capability in CAPABILITIES.values() for action in capability["actions"]
        }
        self.assertEqual(set(schema["properties"]["action"]["enum"]), runtime_actions)
        self.assertFalse(schema["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
