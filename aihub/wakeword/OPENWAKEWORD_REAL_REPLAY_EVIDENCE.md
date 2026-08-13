# Okja v3 openWakeWord compatibility replay evidence

**Status:** partial evidence for G2.5 and G2.16; the alternative-runtime path is verified, but a real v4 replay and a full alternative-engine benchmark are still required.

## Provenance

- Replay workflow run: `31670716561` (`completed / success`)
- Adapter/workflow commit: `4c59e9ea612190ec9bd80ccc7ac8562450f5577a`
- Unit-test workflow run: `31670716607` (`completed / success`, 32 tests)
- Runtime: `openwakeword==0.6.0`, ONNX execution on CPU
- Feature-model source: official openWakeWord `v0.5.1` release assets
- `embedding_model.onnx` SHA-256: `70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f`
- `melspectrogram.onnx` SHA-256: `ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f`
- Initialization seed: NumPy `0`, passed explicitly because openWakeWord `0.6.0` initializes its feature buffer from random PCM
- Classifier source: run `31583273747`, artifact `9136765226`
- Classifier SHA-256: `3cff1a6c54e2eece99f3b61e0238a51b317019d5c1bf214e2c1bddf80998bb7b`
- Audio source: run `31615755020`, artifact `9149302273`, `smoke_melotts_01.wav`
- Audio SHA-256: `a9551898057bfc145002e7e4c0abffff759f450a67e706465d70a18953c5f2a0`
- Audio format/duration: mono PCM16, 16 kHz, 2390 ms
- Replay settings: 1280-sample (80 ms) frames, 2000 ms debounce, 3 fresh-process repeats per threshold

## Result

| Threshold | Detection count | First timestamp | Score | Deterministic |
|---:|---:|---:|---:|:---:|
| 0.50 | 1 | 1280 ms | 0.5055038929 | yes, 3/3 identical |
| 0.06 | 1 | 560 ms | 0.0630315244 | yes, 3/3 identical |

The same classifier and audio produce different scores and timestamps from the LiveKit replay because openWakeWord supplies a different streaming feature-extraction and window-initialization path. These scores are therefore engine-specific compatibility evidence, not interchangeable classifier metrics.

The threshold `0.06` detection occurs while the 16-frame classifier window still contains seeded initialization history. Retain it for exact runtime reproducibility, but do not interpret it as standalone model-quality evidence. The single positive clip also cannot reverse the v3 rejection, which is based on unacceptable false positives per hour on the validation set.

## Failure history

- Run `31669829292` failed because the `openwakeword==0.6.0` wheel did not contain the two feature-model files.
- Run `31670415071` loaded explicit official feature models but failed the repeat guard because the runtime's random feature-buffer initialization was uncontrolled.
- Run `31670716561` pinned both feature-model hashes and initialization seed `0`, then passed all hash, replay, determinism and artifact-upload steps.

## Gate impact

- G2.5: the alternative local/open engine portion is now evidenced. Keep the gate unchecked until a pinned real v4 classifier replays this exact audio SHA.
- G2.16: this is a compatibility replay on one positive clip, not the required full benchmark. Keep the gate unchecked until openWakeWord is evaluated on the shared positive, hard-negative and long-negative benchmark with recall/FRR, FPPH and latency/resource reporting.
