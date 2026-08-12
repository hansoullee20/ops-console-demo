# Okja v4 Pronunciation QC Log

## 2026-08-13 KST — Chatterbox Korean smoke, initial human review

Source workflow family: `Okja v4 Data Smoke`  
Reviewed engine: Chatterbox multilingual / default unconditioned voice  
Review type: human listening QC

### Results

| Clip | Canonical text | Human result | Status | Action |
|---|---|---|---|---|
| `smoke_chatterbox_01` | `옥자` | Wake word was too abrupt/fast, with insufficient lead-in and tail margin. | FAIL | Do not admit to training. Add deterministic pre/post silence and regenerate audition variants. |
| `smoke_chatterbox_02` | `옥자야, 지금 몇 시야?` | Initial `옥자` sounded closer to `입자`; pronunciation not acceptable. | FAIL | Quarantine as positive training data. Regenerate with alternate phrase-boundary/punctuation inputs and re-review. |
| `smoke_chatterbox_03` | `오늘 저녁은 뭐 먹을까?` | More acceptable than clips 1–2, though not highly natural. | REVIEW | Keep only as smoke/QC evidence pending broader quality review. |
| `smoke_chatterbox_04` | `옥수수 좀 사 와.` | More acceptable than clips 1–2, though not highly natural. | REVIEW | Keep only as smoke/QC evidence pending broader quality review. |

### Decision

- Automated WAV QC passing does **not** imply pronunciation acceptance.
- Korean positive clips 1–2 from this review are not training-safe.
- The generator will add fixed context margins and preserve canonical text separately from the TTS synthesis input.
- New positive audition variants will use alternate punctuation/phrase boundaries and must receive another human listening review before G1 pronunciation QC can pass.
- Do not mark `G1.5` or `G1.10` complete from automated CI alone.

### Follow-up implementation

Commit `f8fae103896ac94c43e9947eb0030101b736a418` adds:

- 350 ms pre-silence;
- 550 ms post-silence;
- separate `tts_input_text` provenance;
- multiple Korean positive phrase-boundary audition variants.
