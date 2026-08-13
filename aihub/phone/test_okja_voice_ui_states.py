import pathlib
import unittest

from okja_voice_ui_states import (
    STATES,
    automatic_wake_allowed,
    manual_talk_enabled,
    microphone_allowed,
)


class VoiceUiStateTests(unittest.TestCase):
    def test_mic_off_disables_every_microphone_entrypoint(self):
        self.assertFalse(microphone_allowed("MIC_OFF"))
        self.assertFalse(manual_talk_enabled("MIC_OFF"))
        self.assertFalse(automatic_wake_allowed("MIC_OFF"))

    def test_degraded_and_recovery_states_keep_retry_paths_available(self):
        for state in ("OFFLINE_DEGRADED", "ERROR_RECOVERY"):
            self.assertTrue(microphone_allowed(state))
            self.assertTrue(manual_talk_enabled(state))
            self.assertTrue(automatic_wake_allowed(state))

    def test_thinking_blocks_manual_reentry(self):
        self.assertTrue(microphone_allowed("THINKING"))
        self.assertFalse(manual_talk_enabled("THINKING"))
        self.assertFalse(automatic_wake_allowed("THINKING"))

    def test_android_mirror_contains_all_contract_states(self):
        java = pathlib.Path("../app/src/main/java/com/soul/aihub/VoiceUiState.java").read_text(encoding="utf-8")
        for state in STATES:
            self.assertIn(state, java)
        self.assertIn("state != State.MIC_OFF", java)

    def test_unknown_state_fails_closed(self):
        with self.assertRaises(ValueError):
            microphone_allowed("MAYBE")


if __name__ == "__main__":
    unittest.main()
