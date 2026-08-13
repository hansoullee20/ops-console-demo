# Okja v3 real offline replay evidence

**Status:** partial evidence for G2.5; v3 path verified, v4 and an alternative engine still required.

## Provenance

- Replay workflow run: `31669141305` (`completed / success`)
- Adapter/test commit: `0d6f7188fc15d05a31045944b9d4d240877d3148`
- Unit-test workflow run: `31669141480` (`completed / success`, 25 tests)
- Runtime: `livekit-wakeword==0.2.1`
- Model source: run `31583273747`, artifact `9136765226`
- Model SHA-256: `3cff1a6c54e2eece99f3b61e0238a51b317019d5c1bf214e2c1bddf80998bb7b`
- Audio source: run `31615755020`, artifact `9149302273`, `smoke_melotts_01.wav`
- Audio SHA-256: `a9551898057bfc145002e7e4c0abffff759f450a67e706465d70a18953c5f2a0`
- Audio format/duration: mono PCM16, 16 kHz, 2390 ms
- Replay settings: 1280-sample (80 ms) frames, 25-frame (2 s) sliding window, 2000 ms debounce, 3 identical repeats per threshold

## Result

| Threshold | Detection count | First timestamp | Score | Deterministic |
|---:|---:|---:|---:|:---:|
| 0.50 | 0 | — | — | yes, 3/3 identical |
| 0.06 | 1 | 2000 ms | 0.1658398509 | yes, 3/3 identical |

The result is consistent with the existing v3 rejection: the normal 0.50 threshold misses this approved synthetic `옥자` sample, while the trainer-selected 0.06 threshold detects it but was already measured at an unacceptable 310.0269 FPPH on the v3 validation set. This replay is reproducibility evidence, not a reversal of the v3 model verdict.

## G2.5 closure condition

Do not close G2.5 from this run alone. Replay this exact audio SHA through a pinned v4 model and at least one pinned local/open alternative engine, then retain equivalent manifests and detection JSONL for all three engines.
