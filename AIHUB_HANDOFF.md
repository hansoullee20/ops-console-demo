# AI Hub / Okja — Project Handoff

**Last updated:** 2026-08-12 (KST)  
**Repository:** `hansoullee20/ops-console-demo`  
**Working branch:** `aihub-voice-test`  
**Primary project directory:** `aihub/`  
**Start here after a new chat/session:** this file, then `aihub/README.md`, then `aihub/app/src/main/java/com/soul/aihub/MainActivity.java`.

---

## 1. What this project is

AI Hub is a DIY, always-on Android smart display / voice assistant intended to become a low-cost family-care hub.

The immediate prototype is running on a Samsung Galaxy Z Fold4. The long-term target is a cheap standalone Android device with approximately a 7-inch display, front camera, microphone, speaker, Wi-Fi, and enough RAM/storage to run the local voice front end plus a persistent Claude session.

The design goal is **no per-token API billing where practical**. The current cloud reasoning path uses the user's existing Claude Max subscription through Claude Code / Claude Agent SDK, not a conventional metered API key path. Wake-word and speaker-ID components should be **fully free/open-source and local**.

The original rough finished-device cost target is around **KRW 40,000**, but hardware should not be selected until the real minimum RAM/CPU/storage requirements are measured.

---

## 2. Current architecture

```text
Android native SpeechRecognizer
        ↓
Wake phrase prototype
        ↓
Android native SpeechRecognizer (command)
        ↓
TCP 127.0.0.1:8765
        ↓
Ubuntu PRoot inside Termux
        ↓
persistent Claude Agent SDK client
        ↓
Claude response
        ↓
Android native TTS
```

Current local protocol:

- localhost: `127.0.0.1`
- port: `8765`
- 4-byte big-endian payload length
- UTF-8 JSON payload

Example request:

```json
{
  "profile": "personal",
  "language": "ko-KR",
  "text": "오늘 일정 알려줘"
}
```

The same length-prefixed format is used for the UTF-8 response.

---

## 3. Hardware / test device

Current prototype device:

- Samsung Galaxy Z Fold4
- model: `SM-F936N`
- Android 16
- ARM64 / aarch64
- Snapdragon 8+ Gen 1 class SoC
- approximately 10 GiB RAM visible to Termux
- 8 GiB swap visible in the current environment
- Termux Google Play build: `googleplay.2026.06.21`
- `$PREFIX=/data/data/com.termux/files/usr`
- not rooted

Current rough final-device planning target, **not yet frozen**:

- ARM64
- 4 GB physical RAM preferred for safety
- 3 GB may be possible only after measurement
- 2 GB is considered risky
- 32 GB storage likely sufficient
- Android 10/12+ class system preferred
- Wi-Fi, microphone, speaker, front camera

Do not trust marketplace listings that advertise large amounts of "RAM" without confirming physical RAM versus virtual memory expansion.

---

## 4. Termux / Ubuntu / Claude setup that worked

### Termux

The Google Play Termux build is being used. `termux-api` is installed inside Termux. A separate Termux:API companion app is not required for this Play build.

### Ubuntu PRoot

```bash
pkg install proot-distro -y
proot-distro install ubuntu
proot-distro login ubuntu
```

Inside Ubuntu:

```bash
apt update
apt install curl ca-certificates -y
curl -fsSL https://claude.ai/install.sh | bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
claude --version
```

Claude Code was installed successfully at approximately:

```text
/root/.local/bin/claude
```

Observed Claude Code version during setup:

```text
2.1.227
```

The user authenticated Claude Code with the existing Claude Max account. Interactive `claude` works.

### Claude Agent SDK persistent environment

```bash
python3 -m venv ~/claude-sdk
source ~/claude-sdk/bin/activate
python -m pip install -U pip
python -m pip install claude-agent-sdk
```

Observed installed SDK version during testing was around `0.2.135`.

Persistent-client benchmark was much faster than repeatedly launching `claude -p`.

Observed persistent timings:

```text
ready
ONE   2.89 s
TWO   1.51 s
THREE 1.46 s
```

Observed persistent Sonnet app requests later were approximately:

```text
2.69 s
2.18 s
average ≈ 2.44 s
```

Peak local RSS observed for Claude CLI/session startup was roughly 297–299 MB.

The important conclusion is: **keep the Claude SDK client alive persistently**. Do not use one fresh `claude -p` process per user command.

---

## 5. Bridge files and launch path

Relevant repo files:

```text
aihub/phone/aihub_bridge.py
aihub/phone/start_bridge.sh
```

Typical phone-side sync command used previously:

```bash
curl -fsSL \
  "https://raw.githubusercontent.com/hansoullee20/ops-console-demo/aihub-voice-test/aihub/phone/aihub_bridge.py" \
  -o ~/aihub_bridge.py
```

Then, inside Ubuntu:

```bash
source ~/claude-sdk/bin/activate
python ~/aihub_bridge.py
```

Expected listener:

```text
127.0.0.1:8765
```

Important: at one point the phone's local `~/aihub_bridge.py` was older than the GitHub version. If language/model behavior looks wrong, **compare the local bridge against the branch version before debugging anything else**.

---

## 6. Android app / repo layout

Main project files:

```text
aihub/settings.gradle
aihub/build.gradle
aihub/app/build.gradle
aihub/app/src/main/AndroidManifest.xml
aihub/app/src/main/java/com/soul/aihub/MainActivity.java
aihub/phone/aihub_bridge.py
aihub/phone/start_bridge.sh
aihub/README.md
.github/workflows/aihub-build.yml
```

Android namespace / app ID:

```text
com.soul.aihub
```

Current Android build settings include:

```text
compileSdk 36
minSdk 26
targetSdk 36
```

The app currently uses native Android:

- `SpeechRecognizer`
- `RecognizerIntent`
- `TextToSpeech`

The Android app talks to the persistent bridge through localhost TCP.

---

## 7. What has already been proven working

These are completed proof points, not design assumptions:

1. Native Android Korean STT works.
2. Native Android English STT works.
3. Android app can connect to the Ubuntu PRoot bridge over `127.0.0.1:8765`.
4. Persistent Claude Agent SDK responses work.
5. Android native TTS speaks the returned response.
6. Full STT → Claude → TTS round trip has worked in Korean.
7. Full English recognition path has worked; an earlier wrong-language response was traced to an older local bridge prompt, not the Android STT path.
8. A hands-free wake-phrase prototype using repeated Android `SpeechRecognizer` has been built and installed.
9. The user explicitly reported: **"웨이크워드 성공" (wake word succeeded).**
10. GitHub Actions successfully builds a debug APK from this branch.

A known successful wake-phrase build before the later Vosk probe work was:

```text
commit: 9696420e605c328ea5224c9ed293f2e135d0b4c9
message: Add hands-free wake phrase prototype
workflow run: 31486057087
artifact name: aihub-dual-profile-debug-apk
artifact id: 9099159688
artifact SHA256: be08e97b17e28fe8880524093bc7b4c5c18ae297ccb154de295246fbd14284ee
```

---

## 8. Wake-word decision — current product name is Okja

The wake name has now been unified.

Canonical name:

```text
옥자 / Okja
```

Desired accepted phrases include:

```text
옥자
옥자야
Okja
Hey Okja
Okay Okja
헤이 옥자
오케이 옥자
```

All of these should resolve internally to one wake event, e.g.:

```text
WAKE_OKJA
```

Do **not** maintain separate end-user products called "AI Hub" and "옥자". The intended direction is one app / one firmware with user profiles behind the same wake identity.

The UI/project may still contain older labels such as `AI Hub`, `personal`, and `grandma`; these are legacy prototype naming and should not be mistaken for the final product split.

---

## 9. User identity and room identity are separate concepts

The intended architecture is:

```text
Wake word
  ↓
Speaker / Voice ID
  ↓
Room / device context
  ↓
Command risk / permission policy
  ↓
Action
```

Two different identities must not be conflated:

```text
Device identity = where the device is / which room it controls
User identity   = who is speaking
```

Long-term data model:

```text
Device
- device_id
- room
- connected TV/lights/appliances
- default volume

User
- voiceprint
- name
- preferred language
- preferred model
- TTS speed / text size
- paired phone
- contact permissions
- emergency contacts
- personalized memory

Policy
- per-user command permissions
- allowed actions by Voice ID confidence
```

Speaker ID must **not** be treated as perfect security. TV/replayed audio can spoof voice. Low-risk questions can proceed on uncertain identity; sensitive actions should require stronger confidence / confirmation. Emergency phrases must not be blocked simply because speaker identification fails.

---

## 10. Important product requirements already discussed

These are design requirements, not yet implemented:

- User and grandmother may be in the same room.
- TV/audio may create false wake commands.
- Device should determine who spoke.
- User should have a companion phone interface.
- Grandmother may also have a companion phone interface.
- Emergency speech on the grandmother device should alert the user's phone.
- User should be able to send status messages such as "집에 가는 중" / "곧 도착" and have the home device display/read them.
- Find-my-phone should be possible.
- Voice calling through a paired phone is desirable.
- Room context should decide which TV/lights/appliances a command refers to.
- Later home automation may involve SmartThings / Google Home / MCP-style integrations.

Do not implement these automatically unless the user explicitly reprioritizes them. They were captured as future requirements.

---

## 11. Current wake-word engineering decision: fully free / open-source only

The user explicitly rejected Porcupine / Eagle because the desired solution should be fully free/open-source with no vendor AccessKey dependency.

Candidates discussed:

- LiveKit WakeWord
- Vosk
- sherpa-onnx
- openWakeWord
- microWakeWord

The immediate engineering approach changed from prematurely selecting a custom KWS stack to first validating the cheapest practical Korean path.

### Vosk probe completed

A GitHub Actions probe downloaded:

```text
vosk-model-small-ko-0.22
```

and checked the model vocabulary through the Vosk model API.

Result:

```text
옥자:     YES  (word id 27578)
옥자야:   NO
헤이:     YES  (word id 45969)
오케이:   YES  (word id 26115)
에이아이: NO
허브:     YES  (word id 43859)
```

This is important because the Korean Vosk model can directly recognize the core token `옥자`, and also contains `헤이` and `오케이`.

**However, Vosk has NOT yet been integrated into the Android app.** This was only a vocabulary feasibility probe.

The successful probe/build baseline before this handoff was:

```text
commit: 8afffc83d2d6b1b1b780fed190b322e23201a6aa
message: Probe Korean Vosk vocabulary via API
workflow run: 31489317608
job: 93771820948
conclusion: success
```

The workflow's temporary Vosk probe step downloads an ~82.8 MB Korean model and installs Python Vosk on the GitHub runner. That is useful for validation but should **not** remain as permanent CI overhead once the wake-word decision is finalized.

---

## 12. Current code reality versus desired architecture

### Current code

`MainActivity.java` still has prototype concepts:

```text
Profile.GRANDMA
Profile.PERSONAL
```

and currently selects older wake phrases by profile, such as:

```text
GRANDMA → 옥자
PERSONAL Korean → 에이아이 허브
PERSONAL English → AI Hub
```

The current wake detector is repeated Android `SpeechRecognizer` sessions and string matching.

### Desired next architecture

Unify wake identity first:

```text
옥자 / Okja
```

Then separate personalization from wake name:

```text
Okja wake
   ↓
Voice ID: user / grandmother / unknown
   ↓
Room profile
   ↓
Command / permissions / model / language
```

Do not create separate binaries for grandmother and personal use unless a future constraint forces it.

---

## 13. Why the current Android SpeechRecognizer wake loop is only a prototype

The repeated `SpeechRecognizer` approach proved the interaction flow, but it is not intended as the final always-on wake engine because:

- it is not designed as a dedicated low-power KWS engine;
- continuous/background microphone behavior on modern Android is constrained;
- TV false positives and long-term stability need dedicated measurement;
- screen-off/background behavior is not yet proven;
- battery/CPU usage on the eventual cheap device matters.

Do not delete the working prototype until a local alternative wins in an A/B test.

---

## 14. Next action — where the previous chat stopped

The previous chat stopped **immediately after the Vosk Korean vocabulary probe succeeded**.

The next high-value engineering task is:

### Build a local free wake-word A/B test without destroying the existing working wake path

Recommended order:

1. Keep the current Android `SpeechRecognizer` wake mode as control / fallback.
2. Add an experimental local wake backend, starting with Vosk because `옥자` was verified in its Korean vocabulary.
3. Accept variants by normalization / phrase composition, e.g. `옥자`, `헤이 옥자`, `오케이 옥자`; handle `옥자야` as a recognition/normalization case rather than assuming it exists as one vocabulary token.
4. Measure on the Fold4:
   - wake success rate
   - misses
   - false positives
   - TV false activations
   - time to wake
   - CPU
   - RAM
   - behavior over 20–30 wake attempts
   - 5–10 full wake → command → Claude → TTS → wake cycles
5. Compare against the current Android SpeechRecognizer prototype.
6. Only after a winner is measured, replace the prototype wake loop.

Do not jump directly to hardware shopping yet.

---

## 15. Stability tasks after the wake backend is chosen

Once local wake detection is stable:

1. foreground-service / always-on design
2. screen-off/background test
3. bridge auto-recovery
4. app/bridge crash recovery
5. boot auto-start
6. low-power measurements
7. speaker / Voice ID
8. room/device profiles
9. phone companion
10. emergency/family messaging
11. TV / SmartThings / home automation
12. GPT/Codex fallback/router if still wanted

Modern Android boot/background microphone restrictions mean boot auto-start should be designed deliberately rather than assumed to work like a desktop daemon.

---

## 16. Speaker ID direction

Speaker identification is a separate problem from speech recognition.

The current likely free/local candidate is `sherpa-onnx` speaker identification / verification on ARM64 Android, but this has **not yet been integrated or benchmarked in this project**.

Do not prematurely train a custom grandmother-specific ASR model. First collect real recognition failures. A correction/normalization layer can solve many cases much more cheaply.

---

## 17. Claude model / routing direction

The working concept before unifying the end-user product was roughly:

```text
grandmother simple profile → Haiku
personal profile           → Sonnet
```

The more important final architecture is user-driven routing, not separate apps.

Longer term, the user wants:

```text
Claude primary
GPT/Codex fallback
```

Potential fallback conditions:

- Claude unavailable
- timeout
- plan/session limit
- task better handled by GPT/Codex

Do not implement this before the always-on voice path is stable unless the user reprioritizes it.

---

## 18. Current GitHub Actions setup

Workflow:

```text
.github/workflows/aihub-build.yml
```

Workflow name:

```text
Build AI Hub test APK
```

Build command:

```bash
gradle -p aihub assembleDebug --stacktrace
```

Artifact name:

```text
aihub-dual-profile-debug-apk
```

The artifact name still reflects the old dual-profile prototype and can be renamed later.

As of the Vosk probe run, the APK build itself still succeeded.

---

## 19. Known pitfalls / do not repeat

- Do not reinstall Termux from F-Droid/GitHub just to get speech APIs. The current Play build worked.
- Do not require root.
- Do not use fresh `claude -p` launches per query; persistent SDK is much faster.
- Do not assume the phone's local `~/aihub_bridge.py` matches GitHub; sync/check it.
- Do not assume `옥자야` is one token in Vosk; the probe showed it is not.
- Do not assume all advertised tablet RAM is physical.
- Do not buy final hardware before measuring the local wake engine.
- Do not split the product into separate grandmother/personal binaries merely because the prototype still has two profile buttons.
- Do not treat Voice ID as authentication-grade security.
- Do not let failed Voice ID block emergency requests.
- Do not throw away the current working SpeechRecognizer wake prototype until the local backend beats it.

---

## 20. Fast restart instructions for the next ChatGPT / Claude session

Tell the next agent:

```text
Repo: hansoullee20/ops-console-demo
Branch: aihub-voice-test
Read AIHUB_HANDOFF.md first.
Then inspect aihub/README.md, MainActivity.java, aihub_bridge.py, and .github/workflows/aihub-build.yml.
Current product wake identity is 옥자 / Okja.
The existing SpeechRecognizer wake prototype already works.
The last completed experiment verified Vosk Korean model vocabulary:
옥자 YES, 헤이 YES, 오케이 YES, 옥자야 NO.
Next task is a free/local Vosk wake-word A/B implementation while preserving the current wake backend as fallback.
```

If exact current code or workflow status matters, read the branch from GitHub rather than relying on chat memory.

---

## 21. One-line project state

**Working end-to-end Android voice assistant + working prototype wake phrase + persistent Claude bridge are complete; the project is now at the transition from repeated Android STT wake detection to a fully free/local `옥자 / Okja` wake backend, with Vosk Korean vocabulary feasibility just verified.**
