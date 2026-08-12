# AI Hub / Okja — Project Handoff

**Last updated:** 2026-08-12 (KST)  
**Repository:** `hansoullee20/ops-console-demo`  
**Working branch:** `aihub-voice-test`  
**Project directory:** `aihub/`  
**Wake-word work:** `aihub/wakeword/`  
**Start here in a new session:** read this file first. Do not assume `main` contains the current Okja work.

> **CURRENT CHECKPOINT:** The Okja v2 LiveKit WakeWord training pipeline has completed end-to-end successfully and exported an ONNX model. **The pipeline is working, but the v2 model itself is not good enough to deploy.** At threshold 0.50 its held-out evaluation was Recall **13.28%** and FPPH **2.66**. The next task is model/data diagnosis and a better training iteration, not Android integration of this v2 model.

---

## 0. Fast restart / find the project immediately

```bash
git clone https://github.com/hansoullee20/ops-console-demo.git
cd ops-console-demo
git checkout aihub-voice-test
cat AIHUB_HANDOFF.md
```

Important paths:

```text
AIHUB_HANDOFF.md                         <- canonical handoff
README.md                                <- branch-root pointer to this project
aihub/README.md                          <- project-local overview
aihub/app/                               <- Android prototype
aihub/phone/                             <- Termux/Ubuntu Claude bridge
aihub/wakeword/                          <- custom Okja wake-word training
.github/workflows/aihub-build.yml        <- Android APK build
.github/workflows/okja-wakeword-v2.yml   <- current v2 wake-word training pipeline
```

When resuming from GitHub, use branch **`aihub-voice-test`**.

---

## 1. Product goal

Build a DIY, always-on Android smart display / voice assistant / family-care hub named **옥자 / Okja**.

Final concept:

- inexpensive standalone Android hardware, roughly Nest-Hub-like;
- ~7-inch display, front camera, microphone, speaker, Wi-Fi;
- local always-listening wake-word front end;
- cloud reasoning without per-token API billing where practical, using the user's existing Claude Max / ChatGPT subscriptions through official CLI/agent paths;
- later speaker/Voice ID, room/device context, phone companion, family messaging, emergency alerts, TV/home automation;
- one app / one firmware, not separate grandmother/personal products.

Original rough completed-unit cost target: about **KRW 40,000**. Do **not** select final hardware until the always-on stack is measured properly on the Fold4 and minimum CPU/RAM/storage are derived from evidence.

---

## 2. Current tested device / environment

Prototype phone:

```text
Samsung Galaxy Z Fold4
SM-F936N
Android 16
ARM64 / aarch64
Snapdragon 8+ Gen 1 (SM8475 class)
~10 GiB RAM visible to Termux
8 GiB swap visible in test environment
not rooted
```

Termux:

```text
Google Play build: googleplay.2026.06.21
PREFIX=/data/data/com.termux/files/usr
termux-api installed
```

Native Android `SpeechRecognizer` and Android `TextToSpeech` have both been tested for Korean/English interaction.

Storage observations during setup:

```text
Ubuntu PRoot ~1.7 GB
Termux PREFIX ~2.5 GB
```

Provisional hardware envelope — **not frozen**:

```text
ARM64
4 GB real RAM preferred
3 GB only if later measurement proves it sufficient
2 GB risky
32 GB storage likely enough
Android 10/12+ class system
Wi-Fi + mic + speaker + front camera
```

Marketplace “virtual RAM” must not be counted as physical RAM.

---

## 3. Working end-to-end assistant architecture

The interaction pipeline already worked end-to-end:

```text
Android native SpeechRecognizer
        ↓
command text
        ↓
length-prefixed TCP on 127.0.0.1:8765
        ↓
Ubuntu PRoot inside Termux
        ↓
persistent Claude Agent SDK client
        ↓
response
        ↓
Android native TTS
```

Wire protocol:

- host `127.0.0.1`
- port `8765`
- 4-byte big-endian payload length
- UTF-8 JSON

Example request:

```json
{"profile":"personal","language":"ko-KR","text":"오늘 일정 알려줘"}
```

The response uses the same length-prefix framing.

The current product architecture should eventually become:

```text
local Okja wake word
→ Voice ID / speaker identity
→ room/device context
→ command STT
→ model/router
→ action / reply
→ TTS/UI
```

---

## 4. Claude / Ubuntu PRoot setup that worked

Native Termux installation of Claude Code through npm failed because of a missing native binary, so Ubuntu PRoot was used.

Termux:

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

Observed Claude Code version during setup: `2.1.227`, installed around `/root/.local/bin/claude`.

Claude Max login works interactively.

Persistent Agent SDK environment:

```bash
python3 -m venv ~/claude-sdk
source ~/claude-sdk/bin/activate
python -m pip install -U pip
python -m pip install claude-agent-sdk
```

Observed SDK version during testing: approximately `0.2.135`.

Important benchmark result: do **not** spawn a fresh `claude -p` for every request.

Observed persistent-client timing:

```text
first request ~2.89 s
next requests ~1.51 s / 1.46 s
persistent Sonnet later ~2.69 s / 2.18 s (avg ~2.44 s)
```

Fresh one-shot `claude -p` calls were much slower (~19–34 s). Claude local process/session startup peak RSS observed around 297–299 MB.

---

## 5. Bridge

Repo files:

```text
aihub/phone/aihub_bridge.py
aihub/phone/start_bridge.sh
```

Typical launch inside Ubuntu:

```bash
source ~/claude-sdk/bin/activate
python ~/aihub_bridge.py
```

Expected listener:

```text
127.0.0.1:8765
```

Current model/profile concept in the bridge:

```text
grandma -> Haiku
personal -> Sonnet
```

Known problem: the bridge initializes persistent clients before opening the TCP server. A Claude initialization timeout (`Control request timeout: initialize`) can therefore prevent the server from opening at all. Later fix should make initialization lazy/resilient and allow one client to recover independently instead of making the whole bridge unavailable.

Also check whether the phone-side `~/aihub_bridge.py` is stale before debugging prompt/language behavior; this happened once already.

GPT/Codex fallback/router remains a later task. Claude-primary works well enough for current wake-word prototyping.

---

## 6. Android project state

Current Java source directory contains:

```text
aihub/app/src/main/java/com/soul/aihub/MainActivity.java
aihub/app/src/main/java/com/soul/aihub/PerfActivity.java
aihub/app/src/main/java/com/soul/aihub/PerfMeter.java
aihub/app/src/main/java/com/soul/aihub/StableTemplateWakeActivity.java
aihub/app/src/main/java/com/soul/aihub/TemplateWakeActivity.java
```

Other main files:

```text
aihub/settings.gradle
aihub/build.gradle
aihub/app/build.gradle
aihub/app/src/main/AndroidManifest.xml
.github/workflows/aihub-build.yml
```

Namespace/app ID: `com.soul.aihub`.

The main Android prototype uses native Android STT/TTS and talks to the local PRoot bridge over localhost.

Legacy prototype names such as `GRANDMA`, `PERSONAL`, and artifact naming may still appear. Do not interpret them as separate final products.

---

## 7. Wake identity / product identity

Canonical wake identity:

```text
옥자 / Okja
```

Desired accepted variants include:

```text
옥자
옥자야
Okja
Hey Okja
Okay Okja
헤이 옥자
오케이 옥자
```

All should eventually normalize to one logical event such as `WAKE_OKJA`.

Design rule:

```text
Device identity = where the device is / what room it controls
User identity   = who is speaking
```

Speaker ID is not a security guarantee. TV/replayed audio can spoof a voice. Emergency phrases must not be suppressed solely because speaker identification confidence is low.

---

## 8. Wake-engine chronology

### A. Android SpeechRecognizer wake loop — interaction proof

Repeated Android `SpeechRecognizer` successfully proved the hands-free interaction path. It is a prototype/control, not the desired final low-power wake engine.

Representative measurements shown in the PERF UI:

```text
00:26  CPU 6.2%  PSS 65.9 MB  Java 2.6 MB
11:03  CPU 7.7%  PSS 75.3 MB  Java 4.8 MB
33:51  CPU 7.9%  PSS 70.2 MB  Java 5.8 MB
```

Critical caveat: the CPU value was the app process over approximately the latest two-second interval, **not a long-run mean**, and Android's external recognition service CPU may not be included.

### B. Local MFCC + DTW template experiment

`TemplateWakeActivity` removed cloud/STT from the waiting loop and used local audio/VAD/MFCC/DTW. It required enrollment and was therefore not preferred as the final consumer experience, but it proved local wake-style processing could run on the phone.

Observed examples:

```text
02:26  CPU 9.9%  PSS 101.7 MB  Java 18.8 MB   (after detections)
15:51  CPU 7.7%  PSS 67.8 MB   Java 7.9 MB
41:12  CPU 3.3%  PSS 80.0 MB   Java 4.0 MB
```

The variation is expected because the displayed CPU number was only a recent interval. A single screenshot must not be treated as sustained average load.

### C. Vosk probe

A Korean Vosk vocabulary probe showed `옥자` exists in `vosk-model-small-ko-0.22`, but Vosk was not adopted as the final KWS direction. It was useful only as a feasibility check.

### D. Open-source KWS decision

User requires the final wake engine to be fully free/open-source and local. Porcupine/Eagle/AccessKey-style vendor dependency is rejected.

Candidates considered included:

```text
LiveKit WakeWord
microWakeWord
openWakeWord
sherpa-onnx
Vosk
```

Current training direction: **LiveKit WakeWord** with custom Korean `옥자 / 옥자야 / Hey Okja` data and ONNX export.

---

## 9. Measurement protocol — do not repeat the earlier mistake

A major process error was discovered: implementation moved faster than the measurement design, and two-second CPU snapshots were overinterpreted. Going forward, define the measurement protocol before drawing conclusions.

For wake-engine comparisons use, at minimum:

```text
same phone
same screen state / brightness
same microphone conditions
>= 10 minutes idle

CPU now
CPU average over 1 minute
CPU average over full run
CPU peak
PSS average
PSS peak
wake attempts
successful wakes
misses
false wakes
TV/noise false activations
wake latency
```

Run at least **20 real wake attempts** before comparing implementations. Do not choose hardware from one screenshot.

`PerfMeter.java` exists, but always verify that it reports the exact metric needed before using the number to make a hardware decision.

---

## 10. LiveKit WakeWord experiments

### v1 / smoke path

An initial free GitHub Actions smoke pipeline using LiveKit WakeWord and multilingual synthetic speech was built primarily to prove that the training/export toolchain could run without paid infrastructure.

Relevant older file:

```text
aihub/wakeword/okja_test_voxcpm.yaml
.github/workflows/okja-wakeword-smoke.yml
```

This path was too heavy/awkward for rapid iteration and was not treated as a production model.

### MeloTTS experiment and v2 path

Current source files in `aihub/wakeword/`:

```text
benchmark_melotts.py
generate_melotts_dataset.py
okja_test_voxcpm.yaml
okja_v2_melotts.yaml
```

Current workflow:

```text
.github/workflows/okja-wakeword-v2.yml
```

The v2 design uses:

```text
MeloTTS-generated speech dataset
→ LiveKit augment / feature extraction
→ conv_attention classifier, small
→ train
→ export ONNX
→ held-out eval
```

`okja_v2_melotts.yaml` currently documents:

```text
target phrases: 옥자, 옥자야, Hey Okja
model_type: conv_attention
model_size: small
steps: 6000
learning_rate: 0.0001
target_fp_per_hour: 0.5
ACAV100M training samples: 0 for this iteration
```

The workflow intentionally skips the ~16 GB ACAV training corpus for rapid/free iteration, while still using LiveKit validation negatives.

---

## 11. CURRENT CHECKPOINT — v2 pipeline succeeded, model quality failed

The latest completed v2 run that matters for resumption is:

```text
workflow: Train Okja Wakeword v2
run ID: 31563550569
run number: 2
branch: aihub-voice-test
head SHA: 7bd3965f8a8f4cb0cb579e1b6bfe8650897377ec
commit message: Fix NLTK English tagger for Okja v2
status: completed
conclusion: success
```

Jobs:

```text
generate-speech  job 94010640908  SUCCESS
train            job 94011579771  SUCCESS
```

The successful run proved all of these stages execute end-to-end on free GitHub-hosted CPU runners:

```text
install MeloTTS CPU environment
→ generate synthetic positive/negative speech
→ upload/restore speech dataset
→ install LiveKit WakeWord CPU environment
→ setup compact dependencies
→ generate background clips
→ augment + feature extraction
→ train conv-attention model
→ export ONNX
→ evaluate
→ upload results
```

Artifacts from that run:

```text
okja-wakeword-v2
artifact ID: 9128914528
size: 312,450 bytes
sha256: a2ed3ac0712d8734ff2df01eb1422d8aabaec328334b13119ccf88f9549c15cb
expires: 2026-08-19

okja-v2-speech
artifact ID: 9128703298
size: 22,963,109 bytes
sha256: f12219300c7a98a7dbc0abad2256f9b4164cffaebea4bf214451dc52fef4b0b3
expires: 2026-08-15
```

The model artifact was downloaded and inspected. It contains:

```text
okja_v2_melotts.onnx             99,190 bytes
okja_v2_melotts.pt               81,315 bytes
okja_v2_melotts_det.png          98,002 bytes
okja_v2_melotts_eval.json           310 bytes
okja_v2_melotts_metrics.json       3,613 bytes
v2_augment.log
v2_background.log
v2_eval.log
v2_export.log
v2_setup.log
v2_train.log
```

Held-out evaluation from `v2_eval.log` / `okja_v2_melotts_eval.json`:

```text
validation positives: 128
validation negatives: 30,404
validation duration: 16.89 hours
threshold: 0.50
recall: 0.1328125  = 13.28%
FPPH: 2.6641
accuracy: 0.5657
AUT: 0.2089
```

The trainer also reported an “optimal” threshold of 0.08 with:

```text
recall: 66.41%
FPPH: 381.15
```

That tradeoff is completely unacceptable for an always-on home wake word.

**Interpretation:** the engineering pipeline succeeded; the current v2 classifier did not. Do not install `okja_v2_melotts.onnx` into the Android app and call the wake-word problem solved. Do not simply retrain the identical configuration.

---

## 12. Immediate next task after this handoff

Start from the v2 failure data, not from the earlier Vosk branch of thought.

Recommended next sequence:

1. Inspect `generate_melotts_dataset.py`, the actual v2 speech splits, augment behavior, and LiveKit feature/class semantics to determine why recall is only ~13% while false positives are still >2/hour.
2. Check for data-domain mismatch, inadequate speaker/prosody diversity, phrase imbalance, train/test leakage or over-separation, negative weighting/class balance, and whether the external MeloTTS dataset is being consumed exactly as intended by LiveKit.
3. Preserve the v2 metrics above as the baseline.
4. Create a v3/data-fix iteration only after identifying the most likely failure mechanism. Do not spend another runner cycle blindly.
5. Evaluate v3 before Android integration. The project config's own target is `target_fp_per_hour: 0.5`; practical recall also needs to be high enough for repeated real-user tests. Do not define “production ready” from workflow success alone.
6. Once an ONNX model has acceptable offline metrics, inspect its exact ONNX input/output signature and LiveKit preprocessing/runtime requirements. Android integration must reproduce the same frontend/features; do not merely drop the ONNX file into the app.
7. Then benchmark the local streaming model on the Fold4 using the fixed measurement protocol and real voices/TV/noise.
8. Only after that derive minimum hardware and shop for the final cheap tablet/display hardware.

This is the correct resume point.

---

## 13. Known completed proof points

Already demonstrated in the project:

```text
native Android Korean STT works
native Android English STT works
Android -> localhost PRoot TCP connection works
persistent Claude Agent SDK works
Claude reply -> Android TTS works
full STT -> Claude -> TTS roundtrip works
hands-free Android SpeechRecognizer wake prototype works
local MFCC/DTW wake experiment works
GitHub Actions builds Android debug APK
GitHub Actions can train/export/evaluate LiveKit custom wake-word models
v2 ONNX export is real and has been inspected
```

Do not redo these proofs unless a code change breaks them.

---

## 14. Known unresolved / future work

Not yet complete:

```text
high-quality registration-free Okja wake model
Android ONNX streaming integration
screen-off / long-duration background stability
foreground-service strategy
boot auto-start
bridge lazy init / crash recovery
speaker / Voice ID
room/device profiles
phone companion
family status messaging
emergency alert flow
find/ring phone
voice calling integration
TV / SmartThings / home automation
Claude/GPT/Codex router/fallback
final hardware selection
```

Voice ID and family-care features are requirements/design direction only; do not claim they exist in the current app.

---

## 15. Important engineering constraints / decisions

Keep these unless the user explicitly changes them:

```text
1. Wake word/product identity is 옥자 / Okja.
2. One app/firmware; profiles sit behind the same wake identity.
3. Wake detection should be local and fully free/open-source.
4. No Porcupine/Eagle AccessKey dependency.
5. Prefer no per-token API billing; exploit subscriptions through official agent/CLI paths where allowed.
6. Final unit should not depend on the home server being online.
7. Do not buy final hardware until resource requirements are measured.
8. Speaker ID is contextual identity, not strong authentication.
9. Emergency handling must not fail closed solely on speaker-ID confidence.
10. Measure long-run averages/false wakes/misses; never conclude from a single two-second CPU snapshot.
```

---

## 16. Useful historical references

Earlier hands-free wake prototype:

```text
commit: 9696420e605c328ea5224c9ed293f2e135d0b4c9
workflow run: 31486057087
artifact id: 9099159688
```

PERF fixes / wake experiments include later commits and activities in the current branch; inspect Git history if a regression must be traced.

The branch-root project discovery files were added/refreshed later so a new agent can find this work immediately:

```text
AIHUB_HANDOFF.md
README.md
aihub/README.md
```

---

## 17. Resume prompt for a fresh ChatGPT / Claude / Codex session

Use this verbatim or close to it:

```text
Resume the Okja AI Hub project from GitHub repo hansoullee20/ops-console-demo,
branch aihub-voice-test. Read AIHUB_HANDOFF.md first, then inspect
aihub/wakeword/okja_v2_melotts.yaml,
aihub/wakeword/generate_melotts_dataset.py, and
.github/workflows/okja-wakeword-v2.yml.

The v2 workflow run 31563550569 completed successfully and exported ONNX,
but offline eval is poor: recall 13.28% and FPPH 2.66 at threshold 0.50.
Do not integrate that model into Android and do not blindly rerun the same
training. First diagnose the data/training mismatch using the v2 config and
metrics, then propose/implement the smallest justified v3 fix.
```

---

## 18. Rule for the next agent

**Do not confuse “GitHub Action succeeded” with “wake-word model succeeded.”**

At this handoff point:

```text
PIPELINE: SUCCESS
ONNX EXPORT: SUCCESS
OFFLINE MODEL QUALITY: FAIL
ANDROID INTEGRATION OF TRAINED MODEL: NOT STARTED
FINAL HARDWARE DECISION: NOT READY
```
