# AI Hub / Okja — Project Handoff

**Last updated:** 2026-08-12 (KST)  
**Repository:** `hansoullee20/ops-console-demo`  
**Working branch:** `aihub-voice-test`  
**Project directory:** `aihub/`  
**Wake-word work:** `aihub/wakeword/`  
**Start here in a new session:** read this file first. If chat memory conflicts with Git, Git is source of truth.

> **CURRENT CHECKPOINT:** Okja v3 Korean-only LiveKit WakeWord diagnostic completed. The pipeline works, but the current MeloTTS-synthetic approach is **not promising enough to integrate into Android**. At threshold 0.50: Recall **4.69%**, FPPH **0.00**. At the trainer's optimal threshold 0.06: Recall **85.35%**, but **310.03 FPPH**. This confirms poor class separation. Do not tune threshold, add training steps, or integrate v2/v3. Change the data domain / speaker diversity or compare a different local KWS path.

---

## 0. Fast restart

```bash
git clone https://github.com/hansoullee20/ops-console-demo.git
cd ops-console-demo
git checkout aihub-voice-test
cat AIHUB_HANDOFF.md
```

Important paths: `AIHUB_HANDOFF.md`, `aihub/README.md`, `aihub/app/`, `aihub/phone/`, `aihub/wakeword/`, `.github/workflows/aihub-build.yml`, `.github/workflows/okja-wakeword-v2.yml`, `.github/workflows/okja-wakeword-v3.yml`.

## 1. Product goal

Build a DIY, always-on Android smart display / voice assistant / family-care hub named **옥자 / Okja**. Target is inexpensive Nest-Hub-like standalone Android hardware with display, front camera, mic, speaker and Wi-Fi; local always-listening wake word; cloud reasoning through existing subscription/official agent paths where practical; later Voice ID, room/device context, companion phone, family messaging, alerts, TV/home automation. One app/firmware, not separate grandmother/personal products.

Original rough completed-unit cost target: ~KRW 40,000. Do not select final hardware until the always-on stack is measured on the Fold4.

## 2. Tested environment

```text
Samsung Galaxy Z Fold4 / SM-F936N
Android 16, ARM64/aarch64
Snapdragon 8+ Gen 1 class
~10 GiB RAM visible to Termux; 8 GiB swap in test environment
not rooted
Termux Google Play build googleplay.2026.06.21; termux-api installed
```

Provisional hardware envelope only: ARM64, 4 GB real RAM preferred, 3 GB only if measured sufficient, 2 GB risky, ~32 GB storage likely enough. Never count virtual RAM as physical RAM.

## 3. Working assistant path

```text
Android SpeechRecognizer
→ command text
→ length-prefixed TCP 127.0.0.1:8765
→ Ubuntu PRoot inside Termux
→ persistent Claude Agent SDK client
→ response
→ Android TTS
```

Protocol: 4-byte big-endian payload length + UTF-8 JSON. Persistent Claude is essential: observed first request ~2.89 s and later ~1.5 s in one test; fresh one-shot `claude -p` was ~19–34 s. Startup peak RSS ~297–299 MB.

Bridge files: `aihub/phone/aihub_bridge.py`, `aihub/phone/start_bridge.sh`. Known bridge issue: clients initialize before TCP server opens, so SDK initialization timeout can prevent server availability. Future fix: lazy/resilient independently recoverable clients.

## 4. Android state

Key Java files:

```text
MainActivity.java
PerfActivity.java
PerfMeter.java
StableTemplateWakeActivity.java
TemplateWakeActivity.java
```

under `aihub/app/src/main/java/com/soul/aihub/`. Namespace/app ID `com.soul.aihub`.

Existing SpeechRecognizer wake path works. Preserve it as control/fallback while local KWS is researched.

## 5. Wake/product identity

Canonical identity: **옥자 / Okja**. Desired eventual variants: `옥자`, `옥자야`, `Okja`, `Hey Okja`, `Okay Okja`, `헤이 옥자`, `오케이 옥자`, normalized to one `WAKE_OKJA` event.

Device identity = where the device is / what it controls. User identity = who is speaking. Speaker ID is not a security guarantee; TV/replay can spoof it, and emergency phrases must not be suppressed solely due to low speaker-ID confidence.

## 6. Wake-engine chronology

- **Android SpeechRecognizer:** proved complete hands-free interaction. Control/fallback, not desired final low-power engine. Earlier PERF CPU figures were short process snapshots, not sustained system averages.
- **MFCC + DTW template:** proved local wake-style processing on Fold4; enrollment UX is unattractive for final consumer use.
- **Vosk probe:** `vosk-model-small-ko-0.22` vocabulary contained `옥자`, `헤이`, `오케이`, `허브`. Feasibility probe, not current final KWS.
- **Requirement:** final wake engine must be fully free/open-source/local. Porcupine/Eagle/AccessKey-style dependency rejected.
- Candidates considered: LiveKit WakeWord, microWakeWord, openWakeWord, sherpa-onnx, Vosk.

## 7. Measurement protocol

Use same phone/screen/microphone/room. Measure >=10 min idle; CPU now, 1-min avg, full-run avg, peak; PSS avg/peak; wake attempts/success/miss; false wakes; TV/audio false activations; latency. Use >=20 real wake attempts and 5–10 full wake→command→Claude→TTS→wake cycles. Do not choose hardware from short snapshots.

## 8. LiveKit v2 — pipeline success, model failure

```text
run ID: 31563550569
targets: 옥자, 옥자야, Hey Okja
small conv_attention; 6000 steps
ACAV100M training samples: 0
validation: 128 positive / 30,404 negative / 16.89 h
threshold .50: Recall 13.28%, FPPH 2.6641
```

Lower thresholds improved recall but caused massive false positives. v2 is not deployable. Main weaknesses: effectively one synthetic Korean speaker; limited/mixed-language positive base; no ACAV general-speech training features; training warned about missing general speech; earlier background acquisition had a 429 failure.

## 9. LiveKit v3 — Korean-only diagnostic COMPLETE

Purpose: simplify to **`옥자` only**, increase synthetic positive volume and strengthen phrase/general Korean negatives. Diagnostic, not production model.

Commits:

```text
cab553adce4670c9381327d7c5a4c208ae27c3d9  v3 dataset generator
25b6f3fc218a5b9d33f4e79b339e47709a35902b  v3 config
a128dd9a269e2b99dd7081abcbe9edcc545379e0  v3 workflow
```

Workflow result:

```text
Train Okja Wakeword v3 Korean Probe
run ID: 31583273747
head SHA: a128dd9a269e2b99dd7081abcbe9edcc545379e0
completed / success
```

Artifacts:

```text
okja-wakeword-v3-korean-probe
artifact ID 9136765226
390,647 bytes
sha256 adb1f9ab8ca25971a440b2048eca67a2f137e9f4ae0433919bb572896af3a0d9
expires 2026-08-19

okja-v3-korean-speech
artifact ID 9136308340
182,478,146 bytes
expires 2026-08-15
```

### v3 held-out evaluation

```text
positive: 512
negative: 31,236
validation duration: 17.35 h
threshold .50
Recall 4.6875%
FPPH 0.0
Accuracy 0.5234375
AUT 0.0826421
```

Trainer optimal operating point:

```text
threshold .06
Recall 85.3516%
FPPH 310.0269
```

Classifier training completed normally. GitHub runner maximum RSS ~808,912 KB (~790 MiB), classifier training wall time ~1m40s. These are training-runner observations, not Android inference requirements.

### v3 verdict

**FAIL / NOT PROMISING for Android integration.** Predeclared diagnostic target was Recall >=60% AND FPPH <=0.5. v3 cannot achieve both. At a safe threshold it almost never wakes; at useful recall it false-wakes hundreds of times per hour. Score distributions are poorly separated.

This is stronger evidence than “needs more training”: even after simplifying to one Korean word and strengthening synthetic negatives, the normal-threshold recall became worse. Do not spend the next iteration merely increasing steps or changing threshold.

## 10. Next technical decision

Change the data/domain assumption before another LiveKit run.

1. Obtain genuinely diverse Korean positive speech for `옥자`: real recordings and/or a true multi-speaker Korean source. The single-speaker MeloTTS-derived positive domain is the leading suspect.
2. Put broad real/general-speech negatives into the **training sampler**, not only validation. Restore LiveKit's intended general-speech training data if practical.
3. Run a small sanity experiment before spending large runner time.
4. In parallel, compare a simpler Android-ready local baseline (Vosk/open-vocabulary or another KWS path) so LiveKit is not optimized indefinitely without competition.
5. Only after offline Recall/FPPH is credible should a local model be added beside SpeechRecognizer for Fold4 A/B testing.

Recommended next experiment: **real-speaker sanity test**. Collect a small set of `옥자` utterances from multiple real speakers, strictly separate train/test speakers or recordings, and evaluate against broad real speech. If separation improves sharply, synthetic-domain diversity was the main problem. If it still fails badly, stop investing in this LiveKit path and switch KWS engines.

## 11. Do not repeat

- Do not integrate v2/v3 just because ONNX export succeeded.
- Do not confuse pipeline success with model quality.
- Do not threshold-tune v3: useful recall costs ~310 FPPH.
- Do not assume more steps solve a data-domain problem.
- Do not treat rate/pitch variants of one synthetic voice as real speaker diversity.
- Do not select hardware before sustained Fold4 measurements.
- Do not count virtual RAM as real RAM.
- Do not interpret legacy GRANDMA/PERSONAL labels as separate products.
- Do not spawn fresh Claude CLI per request.
- Do not rely on chat memory when Git differs.

## 12. Immediate restart instruction

> Open `hansoullee20/ops-console-demo`, branch `aihub-voice-test`, and read `AIHUB_HANDOFF.md`. v3 Korean-only LiveKit diagnostic is complete and failed quality criteria: Recall 4.69% / FPPH 0 at threshold .50; at threshold .06 Recall 85.35% but FPPH 310.03. Do not integrate v2/v3. Continue by testing genuinely diverse Korean positive data and broad real-speech negatives, while keeping Android SpeechRecognizer as control/fallback.
