# AI Hub / Okja Voice Prototype

> **Canonical project state / restart instructions:** [`../AIHUB_HANDOFF.md`](../AIHUB_HANDOFF.md)  
> **Working branch:** `aihub-voice-test`

## Current checkpoint

The end-to-end Android assistant path works:

```text
Android STT
→ localhost TCP 127.0.0.1:8765
→ persistent Claude Agent SDK in Ubuntu PRoot
→ Android TTS
```

The product/wake identity is unified as:

```text
옥자 / Okja
```

The final wake backend must be local and fully free/open-source.

### Latest wake-word result

LiveKit WakeWord v2 training/export pipeline completed successfully in GitHub Actions:

```text
workflow: .github/workflows/okja-wakeword-v2.yml
run: 31563550569
head SHA: 7bd3965f8a8f4cb0cb579e1b6bfe8650897377ec
pipeline: SUCCESS
ONNX export: SUCCESS
```

But the generated v2 model is **not deployable yet**:

```text
threshold 0.50
recall 13.28%
FPPH 2.66
validation positives 128
validation negatives 30,404
validation duration 16.89 h
```

Therefore the next task is **diagnose/fix the v2 data/training problem and build a justified v3**, not Android integration of the current ONNX file.

Current wake-word sources:

```text
wakeword/benchmark_melotts.py
wakeword/generate_melotts_dataset.py
wakeword/okja_test_voxcpm.yaml
wakeword/okja_v2_melotts.yaml
```

Current Android experiment sources include:

```text
app/src/main/java/com/soul/aihub/MainActivity.java
app/src/main/java/com/soul/aihub/PerfActivity.java
app/src/main/java/com/soul/aihub/PerfMeter.java
app/src/main/java/com/soul/aihub/StableTemplateWakeActivity.java
app/src/main/java/com/soul/aihub/TemplateWakeActivity.java
```

## Do not restart from the old Vosk idea

Vosk was only a feasibility probe. The current engineering line is custom LiveKit WakeWord training with ONNX export. Read [`../AIHUB_HANDOFF.md`](../AIHUB_HANDOFF.md) before making changes; it contains the Fold4 environment, Claude bridge setup, wake performance history, fixed measurement protocol, exact v2 artifacts/metrics, unresolved work, and the next-session resume prompt.
