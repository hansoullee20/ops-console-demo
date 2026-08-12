# Okja v4 — MeloTTS Korean Human QC

**Date:** 2026-08-13 KST  
**Scope:** four-clip MeloTTS Korean smoke artifact from GitHub Actions run `31615755020`  
**Model:** `myshell-ai/MeloTTS-Korean` revision `0207e5adfc90129a51b6b03d89be6d84360ed323`  
**Code:** MeloTTS commit `209145371cff8fc3bd60d7be902ea69cbdb7965a`

## Reviewed clips

1. `옥자.` — positive wake phrase
2. `옥자야. 지금 몇 시야?` — positive wake phrase in command context
3. `오늘 저녁은 뭐 먹을까?` — ordinary negative
4. `옥수수 좀 사 와.` — hard negative / near-phonetic context

## Human listening result

Reviewer feedback after listening to all four smoke clips:

- substantially more natural than the previous Chatterbox Korean samples;
- delivery sounds somewhat like a voice actor;
- quality is acceptable for **initial wakeword data generation**;
- no blocking pronunciation or naturalness issue was reported for this four-clip smoke set.

## Decision

**APPROVED FOR INITIAL V4 DATA USE.**

This approval is deliberately narrow:

- it approves MeloTTS Korean as an independent source for initial positive/negative data and engine-holdout material;
- it does **not** certify production assistant-voice quality;
- it does **not** establish speaker diversity because the Korean model is effectively a single-speaker source;
- larger generated batches still require pronunciation spot checks and quarantine of any bad synthesis;
- TEST D household recordings remain immutable evaluation data and must never be trained on.

## Automated evidence

GitHub Actions run `31615755020` completed successfully. The pipeline generated four clips, assigned them to the explicit engine holdout, passed WAV QC and leakage checks, captured the environment, and uploaded the artifact.
