# G3.31 — Microphone-off / offline / error-state evidence

Status: implemented; close only after the integration-contract CI run is green.

## Scope

G3.31 requires the product voice path to distinguish and test microphone-off, offline/degraded, and recoverable error states. It does not replace the separate Fold4 sustained-use gates G3.29/G3.30/G3.33.

## Implementation

- `VoiceUiState` defines READY, LISTENING, THINKING, MIC_OFF, OFFLINE_DEGRADED and ERROR_RECOVERY.
- MIC_OFF is a true privacy boundary: Android cancels/destroys `SpeechRecognizer`, sets the recognizer reference to null, disables manual talk, prevents automatic wake, clears the active interaction chain and renders an unmistakable microphone-off state.
- Re-enabling microphone access rechecks `RECORD_AUDIO` permission and recreates the recognizer only after permission is available.
- Bridge/socket failure sets `bridgeDegraded=true`, enters OFFLINE_DEGRADED and presents a plain-language retryable state rather than exposing a transport exception as normal assistant output.
- Recognizer availability/start/runtime failures enter ERROR_RECOVERY and preserve a retry path.
- Automatic wake and manual microphone access are guarded by the shared `VoiceUiState` policy.

## Automated evidence

- Policy tests: `aihub/phone/test_okja_voice_ui_states.py`.
- Live Android wiring tests: `aihub/phone/test_android_voice_ui_integration.py` reads the actual `MainActivity.java` and fails if the MIC_OFF destruction/blocking path, permission-gated re-enable path, offline degraded path, recovery path, or shared state guards are removed.
- Android compilation evidence before the integration-contract addition: APK run `31693035202` succeeded for the live `MainActivity` trust-state implementation.
- Integration-contract run: `31693382427` (must be green before G3.31 is marked complete).

## Closure boundary

A green integration-contract run is sufficient for G3.31 because this checklist item is a software state/behavior contract. Physical Fold4 endurance and full-cycle behavior remain explicitly owned by G3.29, G3.30 and G3.33 and must not be inferred from this evidence.
