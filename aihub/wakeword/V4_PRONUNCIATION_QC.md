# Okja v4 Pronunciation / Listening QC

**Status:** ACTIVE  
**Branch:** `aihub-voice-test`  
**Purpose:** Human listening evidence for synthetic wakeword corpus. Automatic WAV QC is necessary but not sufficient.

## Policy

Pronunciation accuracy and audio naturalness are scored separately.

- `pronunciation = PASS` means the intended wake phrase is clearly heard.
- `pronunciation = FAIL` means the intended phrase is missing, substituted, or materially ambiguous.
- `naturalness = REVIEW` means pronunciation may be usable for diagnostics but the voice/timing sounds synthetic or robotic enough that it should not be treated as the sole source for scaled training.
- Any failed positive stays quarantined from training until replaced or explicitly re-approved.

## Human review — 2026-08-13 KST

### Initial Chatterbox smoke

- `smoke_chatterbox_01` — intended `옥자`
  - pronunciation: FAIL
  - observation: standalone wakeword was delivered too quickly / boundary felt clipped; `옥자` was not comfortably resolved.
- `smoke_chatterbox_02` — intended `옥자야, 지금 몇 시야?`
  - pronunciation: FAIL
  - observation: wakeword onset sounded closer to `입자` than `옥자`.
- `smoke_chatterbox_03` — `오늘 저녁은 뭐 먹을까?`
  - pronunciation: PASS/acceptable
  - naturalness: REVIEW
- `smoke_chatterbox_04` — `옥수수 좀 사 와.`
  - pronunciation: PASS/acceptable
  - naturalness: REVIEW

### Run #9 pronunciation audition variants

GitHub Actions run: `31612771436`  
Generator commit: `f8fae103896ac94c43e9947eb0030101b736a418`

- `옥자 variant A`
  - pronunciation: FAIL
  - observation: the intended `옥자` is not clearly articulated; perceptually it sounds closer to `ㅡ자`, with the initial vowel/consonant realization of `옥` weakened or lost.
  - naturalness: REVIEW / robotic
  - disposition: QUARANTINE
- `옥자 variant B`
  - pronunciation: PASS
  - naturalness: REVIEW / robotic
  - disposition: usable for diagnostic comparison, not sufficient as sole scaled-training source
- `옥자야 variant A`
  - pronunciation: PASS
  - naturalness: REVIEW / robotic
  - disposition: usable for diagnostic comparison, not sufficient as sole scaled-training source
- `옥자야 variant B`
  - pronunciation: PASS
  - naturalness: REVIEW / robotic
  - disposition: usable for diagnostic comparison, not sufficient as sole scaled-training source

## Decision

1. Keep pre/post padding; it fixes clip-boundary presentation but does not guarantee correct phoneme realization.
2. Do not attempt to rescue failed `옥자` samples by automatic QC or thresholding.
3. Do not scale Chatterbox as the only Korean positive-sample source while default-unconditioned speech remains noticeably robotic.
4. Prioritize a second independent Korean TTS source and real-human `옥자` recordings for positive-class diversity.
5. Continue using Chatterbox for controlled diagnostic variants and for negatives where pronunciation is acceptable, subject to provenance/license rules.
6. Keep G1.10 human pronunciation QC open until every intended smoke phrase/voice combination that is admitted to training has passed human listening review.
