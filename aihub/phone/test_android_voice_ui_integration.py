import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "src" / "main" / "java" / "com" / "soul" / "aihub" / "MainActivity.java"


class AndroidVoiceUiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = MAIN.read_text(encoding="utf-8")

    def test_mic_off_destroys_recognizer_and_blocks_manual_voice(self):
        source = self.source
        self.assertIn("private void disableMicrophone()", source)
        self.assertIn("recognizer.destroy()", source)
        self.assertIn("recognizer=null", source)
        self.assertIn("renderMicOff()", source)
        self.assertIn("talkButton.setEnabled(false)", source)
        self.assertIn("if(uiState==VoiceUiState.State.MIC_OFF){renderMicOff();return;}", source)

    def test_mic_reenable_requires_permission_and_recreates_recognizer(self):
        source = self.source
        self.assertIn("private void enableMicrophone()", source)
        self.assertIn("checkSelfPermission(Manifest.permission.RECORD_AUDIO)", source)
        self.assertIn("requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},REQ_AUDIO)", source)
        self.assertIn("initSpeech()", source)

    def test_bridge_failure_has_explicit_degraded_state(self):
        source = self.source
        self.assertIn("boolean degraded=false", source)
        self.assertIn("degraded=true", source)
        self.assertIn("bridgeDegraded=degradedResult", source)
        self.assertIn("degradedResult?VoiceUiState.State.OFFLINE_DEGRADED", source)
        self.assertIn("offlinePrompt()", source)
        self.assertNotIn("브리지/이벤트 오류:", source)

    def test_recognizer_failures_enter_recovery_state(self):
        source = self.source
        self.assertIn("VoiceUiState.State.ERROR_RECOVERY", source)
        self.assertIn("음성인식 오류 · 다시 시도합니다", source)
        self.assertIn("음성인식 시작 실패 · 다시 시도합니다", source)

    def test_automatic_wake_and_manual_talk_use_state_policy(self):
        source = self.source
        self.assertIn("VoiceUiState.automaticWakeAllowed(uiState)", source)
        self.assertIn("VoiceUiState.microphoneAllowed(uiState)", source)
        self.assertIn("VoiceUiState.manualTalkEnabled(uiState)", source)


if __name__ == "__main__":
    unittest.main()
