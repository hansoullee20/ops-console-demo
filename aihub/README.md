# AI Hub / Okja Voice Prototype

> Full project state and restart instructions: [`../AIHUB_HANDOFF.md`](../AIHUB_HANDOFF.md)

## Current target

One Android app / firmware, one wake identity:

```text
옥자 / Okja
```

Desired accepted variants include `옥자`, `옥자야`, `Okja`, `Hey Okja`, `Okay Okja`, `헤이 옥자`, and `오케이 옥자`.

Do not interpret the old `GRANDMA` / `PERSONAL` prototype profiles as separate final products. The intended direction is:

```text
Okja wake
  ↓
Voice ID: user / grandmother / unknown
  ↓
Room/device context
  ↓
command policy / model / language
```

## Working end-to-end path

```text
Android SpeechRecognizer
→ wake-phrase prototype
→ Android command STT
→ localhost TCP 127.0.0.1:8765
→ persistent Claude Agent SDK in Ubuntu PRoot
→ Android TTS
```

The wake-phrase prototype has been installed and the user reported that wake detection succeeded.

## Current wake-engine experiment

The final wake backend must be fully free/open-source and local. Porcupine/Eagle were rejected because of vendor AccessKey dependency.

A feasibility probe of `vosk-model-small-ko-0.22` completed successfully. Vocabulary results:

```text
옥자     YES
옥자야   NO
헤이     YES
오케이   YES
에이아이 NO
허브     YES
```

Vosk is **not yet integrated into the Android app**. The next task is to add an experimental local Vosk wake backend while keeping the existing Android `SpeechRecognizer` wake path as a control/fallback, then compare wake rate, false positives, TV activations, CPU, RAM, and latency.

## Bridge

Repo files:

```text
phone/aihub_bridge.py
phone/start_bridge.sh
```

Typical Ubuntu launch:

```bash
source ~/claude-sdk/bin/activate
python ~/aihub_bridge.py
```

Expected listener:

```text
127.0.0.1:8765
```

If behavior differs from the repo, check whether the phone's local `~/aihub_bridge.py` is stale.

## APK build

GitHub Actions workflow:

```text
.github/workflows/aihub-build.yml
```

Build command:

```bash
gradle -p aihub assembleDebug --stacktrace
```

Artifact name currently remains:

```text
aihub-dual-profile-debug-apk
```

The artifact name is legacy prototype naming and can be changed later.

## Next task

Preserve the working wake prototype and build a free/local Vosk A/B wake test for `옥자 / Okja`. Do not shop final hardware until the local wake engine has been measured on the Fold4.
