# AI Hub / Okja — v4 Multi-Engine Synthetic Generalization Test Plan

**Date:** 2026-08-12 KST
**Status:** Approved experimental plan; do not replace the working Android SpeechRecognizer path.

## 1. Question v4 must answer

Can a wake-word model learn the acoustic concept of **옥자 / Okja** from diverse synthetic speech well enough to generalize to voices and TTS engines that were never present in training?

v4 is NOT a production-model attempt. It is a falsifiable diagnostic experiment after v2/v3 showed that single-speaker MeloTTS-derived Korean data did not separate positives from general speech.

## 2. Licensing gate

Only sources whose model/voice/text rights are explicitly compatible with the intended experiment may enter the durable corpus.

### Green, reverified 2026-08-12

- **ResembleAI Chatterbox Multilingual V3** — upstream repository states MIT license; multilingual model explicitly supports Korean (`ko`) and English (`en`). Use as the primary Korean+English synthetic engine.
- **Kokoro-82M** — official Hugging Face model is marked Apache-2.0; official voice inventory currently lists 20 American-English voices and 8 British-English voices. Use for English diversity and as an engine-level holdout where useful.
- **Original scripts authored specifically for Okja** — preferred source for modern household/conversational text because it avoids third-party text copyright uncertainty.

### Conditional / not part of the first v4 run

- Public-domain literature may be added only after work-by-work jurisdiction verification. Project Gutenberg determines public-domain status under US law and explicitly warns non-US users to check local law. Therefore Gutenberg text is not required for v4 phase 1.
- Korean public-domain/expired-rights literature can be added later after recording the exact work, author, source, rights statement, and retrieval date in a corpus manifest.
- Any additional TTS engine/model must pass a separate license review for code, model weights, voice assets/reference audio, and generated-output restrictions before its samples are mixed into the durable corpus.

### Reject / quarantine rule

Do not mix samples from a source with unclear/noncommercial-only model or voice terms into the durable v4 corpus. Experimental samples from an unclear source, if ever generated, must live in a separate quarantine directory and cannot be used for product training.

## 3. Text design

The first v4 corpus should use mostly original modern conversational scripts rather than literature.

### Positive wake forms

Korean:
- 옥자
- 옥자야
- 헤이 옥자
- 오케이 옥자
- 옥자, 지금 몇 시야?
- 옥자야, 불 좀 켜줘.
- 옥자, 내 휴대폰 찾아줘.

English:
- Okja
- Hey Okja
- Okay Okja
- Okja, what time is it?
- Hey Okja, where is my phone?
- Okja, turn the light on.

Generate many original command continuations, but keep the wake prefix/phrase labels explicit.

### Ordinary negatives

Generate original modern household dialogue covering:
- family conversation
- TV-like dialogue
- kitchen/meal talk
- phone-call language
- questions and answers
- time/numbers/dates
- names and locations
- casual commands not addressed to Okja
- Korean-English code switching
- monologue/news-like speech

### Hard negatives

Create phrases containing acoustically similar material but not the intended wake phrase. Maintain these in a manually reviewed list; do not assume spelling similarity equals acoustic similarity.

### Mention/context set — separate from negatives

Sentences that literally contain the target word but are not intended as device invocation must NOT be silently labeled ordinary negative. Examples:
- 어제 옥자라는 영화를 봤어.
- 옥자라는 이름을 들어봤어?
- I watched Okja last night.

Keep these as a separate `mention_context` evaluation class. Whether these should wake the product is a product-policy question beyond simple keyword presence.

## 4. Corpus sizes — phase 1

Keep the first run small enough to finish quickly and expose pipeline mistakes before scaling.

Target approximately:
- Korean positive: 1,000–2,000 clips
- English positive: 1,000–2,000 clips
- Korean ordinary/hard negative: 6,000–10,000 clips
- English ordinary/hard negative: 6,000–10,000 clips
- mention/context: >=200 Korean + >=200 English

If generation/training is stable and generalization is visible, scale in phase 2.

## 5. Engine and voice split

The split must prevent synthetic leakage.

### Korean

Primary generation: Chatterbox Multilingual V3 (`ko`).

Because a second independently licensed Korean engine is not yet reverified for this plan, do NOT pretend that Chatterbox speaker variations constitute engine diversity. v4 phase 1 can validate pipeline/data construction, but a true Korean engine-holdout test requires another independently verified Korean TTS engine or real speakers.

If Chatterbox voice cloning/reference conditioning is used, only use reference clips we own or have explicit rights to use. Record source/rights metadata in the manifest.

### English

Use Chatterbox Multilingual V3 (`en`) and Kokoro-82M.

Hold out complete Kokoro voices from training. Prefer an additional experiment where an entire engine is held out: train with Chatterbox English and evaluate on Kokoro, then reverse if practical.

## 6. Required split hierarchy

Never randomly split clips after generating near-duplicates.

Split first by source identity:
1. TTS engine
2. voice/reference identity
3. base script
4. acoustic augmentation seed

No base utterance, voice identity, or near-duplicate augmentation family may cross train/test boundaries.

Evaluation layers:
- **Test A:** unseen synthetic voices
- **Test B:** unseen synthetic engine where possible
- **Test C:** real human Okja recordings; never train on the initial benchmark subset
- **Test D:** long-form household ambient recordings; fixed benchmark, never train on the benchmark copy

## 7. Acoustic augmentation

Apply only to a controlled subset and preserve clean originals.

Candidate augmentations:
- room impulse response / reverb
- simulated distance / level attenuation
- TV/speaker-like EQ
- background conversation
- music
- kitchen/household noise
- low-volume speech
- codec/compression degradation

Record every transformation and seed in the manifest. Never allow an augmented derivative of a test clip into training.

## 8. Metrics

Primary:
- Recall / miss rate by wake variant
- False positives per hour (FPPH)
- Precision where event labels permit
- score distributions for positive, ordinary negative, hard negative, and mention/context
- threshold curves, not one cherry-picked threshold

Break down results by:
- language
- engine
- held-out voice
- wake phrase variant
- clean vs augmented
- distance/noise condition when available

Do not declare success from synthetic validation alone.

## 9. Real-world benchmark plan

Create a fixed household benchmark independent of training.

Preferred capture:
- 1–3 devices in realistic Okja positions
- start with 4–6 hours to validate capture/analysis, then extend to ~24 hours
- include deliberate wake attempts spread across distance, direction, volume, TV/music/kitchen/conversation conditions
- keep a timestamped event log for deliberate wake attempts

For long recordings, run the model offline over the entire stream and save only diagnostic windows around model triggers/misses for review. Suggested event window: ~3 seconds before trigger + ~2 seconds after.

The fixed household benchmark must remain untouched by training so v4/v5/other KWS engines can be compared on identical audio.

## 10. Decision gates

### Gate 0 — pipeline sanity

Before large generation, manually listen to a random sample from every engine/language/label. Reject malformed pronunciation, silence, clipping, wrong language, or obvious synthesis failure.

### Gate 1 — synthetic generalization

Proceed only if held-out voices/engine show meaningful class separation. Do not use training-set accuracy as evidence.

### Gate 2 — real-human sanity

Test on a small real-human benchmark. If synthetic performance is strong but real-human performance collapses, synthetic domain mismatch remains and scaling synthetic volume is not justified.

### Gate 3 — household false positives

Run against long-form household audio. Product viability depends on FPPH under realistic Korean TV/conversation/noise, not only isolated clips.

### Gate 4 — Android shadow mode

Only after Gates 1–3 show useful separation should the model be placed beside SpeechRecognizer on Fold4 in shadow mode. Do not replace the working control path yet.

## 11. v4 implementation order

1. Build a machine-readable `sources_manifest` containing source URL/name, version/commit, license, allowed role, and verification date.
2. Build original Korean/English conversational script generators and hand-reviewed wake/hard-negative/mention templates.
3. Implement Chatterbox Korean+English generation.
4. Implement Kokoro English generation with explicit voice IDs.
5. Implement corpus QC: duration, silence, clipping, language/pronunciation spot checks, duplicate/near-duplicate checks.
6. Freeze source/voice/script splits BEFORE augmentation.
7. Generate a small phase-1 corpus.
8. Train/evaluate with LiveKit WakeWord using the same classifier family initially so the data change is isolated from model change.
9. Evaluate unseen voices/engine and real-human samples.
10. Run the frozen model over household long-form audio.
11. Only then decide whether to scale v4, build v5 with real/multi-speaker Korean, or change KWS engines.

## 12. What v4 must NOT do

- Do not add more MeloTTS pitch/rate variants and call them new speakers.
- Do not mix unverified model/voice licenses into the durable corpus.
- Do not use a random clip-level split that leaks the same TTS voice/script into train and test.
- Do not use the 24-hour household benchmark as training data.
- Do not label literal `옥자/Okja` mentions as ordinary negatives without a separate product-policy decision.
- Do not tune only for recall while ignoring FPPH.
- Do not integrate v2/v3 into Android.
- Do not choose final cheap hardware from training-runner resource use.

## 13. Immediate next engineering task

Implement only the **corpus builder + source manifest + phase-1 generation/QC** first. Do not launch a large training run until the generated sample audit passes.

After phase-1 corpus QC, run a small LiveKit sanity training job and inspect held-out synthetic and real-human separation before scaling.
