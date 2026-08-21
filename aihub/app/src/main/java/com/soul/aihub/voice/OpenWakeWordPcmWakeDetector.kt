package com.soul.aihub.voice

/**
 * Score provider for one openWakeWord classifier.
 *
 * The concrete ONNX implementation owns model/feature runtime state only. It must
 * never acquire the microphone. Input is exactly one 16 kHz PCM16 inference window.
 * [reset] must clear any stateful feature/history buffers so PCM discontinuities can
 * fail closed instead of leaving hidden model context spanning the gap.
 */
interface OpenWakeWordFramePredictor : AutoCloseable {
    val modelName: String
    fun predict(pcm16: ShortArray): Float
    fun reset() = Unit
    override fun close() = Unit
}

/**
 * Caller-owned-PCM adapter for the openWakeWord streaming contract used by Okja's
 * deterministic Python replay (`openwakeword_replay_adapter.py`).
 *
 * AudioEngine emits 20 ms / 320-sample frames while the pinned openWakeWord replay
 * consumes 80 ms / 1280-sample windows. This adapter performs only the framing,
 * continuity and debounce policy; model preprocessing/inference stays behind
 * [OpenWakeWordFramePredictor]. It never opens AudioRecord.
 *
 * A PCM discontinuity drops any partial 80 ms window and resets predictor history
 * instead of stitching model context from opposite sides of a gap. Both monotonic
 * frame sequence and sample-position continuity are required, matching the shared
 * [PcmContinuityTracker] contract used elsewhere in the voice pipeline.
 */
class OpenWakeWordPcmWakeDetector(
    private val predictor: OpenWakeWordFramePredictor,
    private val keyword: String = "옥자야",
    private val threshold: Float = 0.50f,
    private val sampleRateHz: Int = 16_000,
    private val inferenceWindowSamples: Int = DEFAULT_INFERENCE_WINDOW_SAMPLES,
    debounceMs: Int = DEFAULT_DEBOUNCE_MS,
) : WakeDetector {
    init {
        require(keyword.isNotBlank()) { "keyword must not be blank" }
        require(predictor.modelName.isNotBlank()) { "predictor modelName must not be blank" }
        require(threshold.isFinite() && threshold in 0.0f..1.0f) {
            "threshold must be finite and within [0, 1]"
        }
        require(sampleRateHz == 16_000) { "openWakeWord Okja adapter currently requires 16 kHz PCM" }
        require(inferenceWindowSamples > 0) { "inferenceWindowSamples must be positive" }
        require(debounceMs >= 0) { "debounceMs must be non-negative" }
    }

    private val debounceSamples =
        (sampleRateHz.toLong() * debounceMs.toLong() / 1_000L).coerceAtLeast(0L)
    private val continuity = PcmContinuityTracker()
    private val window = ShortArray(inferenceWindowSamples)
    private var bufferedSamples = 0
    private var lastDetectionEndSampleIndex: Long? = null
    private var closed = false

    override fun accept(frame: PcmFrame): WakeDetection? {
        check(!closed) { "detector is closed" }

        val continuityStatus = continuity.observe(frame)
        if (!continuityStatus.continuous) {
            // Never construct an inference window or hidden feature history from PCM
            // separated by a gap, duplicate, or out-of-order frame. Checking both the
            // sequence and sample index prevents sequence-only discontinuities from
            // silently carrying model state across an invalid stream boundary.
            bufferedSamples = 0
            lastDetectionEndSampleIndex = null
            predictor.reset()
        }

        if (frame.samples.isEmpty()) return null

        var sourceOffset = 0
        var firstDetection: WakeDetection? = null
        while (sourceOffset < frame.samples.size) {
            val copyCount = minOf(
                inferenceWindowSamples - bufferedSamples,
                frame.samples.size - sourceOffset,
            )
            frame.samples.copyInto(
                destination = window,
                destinationOffset = bufferedSamples,
                startIndex = sourceOffset,
                endIndex = sourceOffset + copyCount,
            )
            bufferedSamples += copyCount
            sourceOffset += copyCount

            if (bufferedSamples == inferenceWindowSamples) {
                val score = predictor.predict(window.copyOf())
                require(score.isFinite() && score in 0.0f..1.0f) {
                    "openWakeWord predictor returned invalid score: $score"
                }

                val windowEndSampleIndex = frame.startSampleIndex + sourceOffset.toLong()
                val previousDetection = lastDetectionEndSampleIndex
                val outsideDebounce = previousDetection == null ||
                    windowEndSampleIndex - previousDetection >= debounceSamples

                if (score >= threshold && outsideDebounce) {
                    lastDetectionEndSampleIndex = windowEndSampleIndex
                    if (firstDetection == null) {
                        firstDetection = WakeDetection(
                            keyword = keyword,
                            detectedAtElapsedRealtimeNs = frame.capturedAtElapsedRealtimeNs,
                            score = score,
                        )
                    }
                }

                bufferedSamples = 0
            }
        }

        return firstDetection
    }

    fun reset() {
        check(!closed) { "detector is closed" }
        continuity.reset()
        bufferedSamples = 0
        lastDetectionEndSampleIndex = null
        predictor.reset()
    }

    override fun close() {
        if (closed) return
        closed = true
        continuity.reset()
        bufferedSamples = 0
        lastDetectionEndSampleIndex = null
        predictor.close()
    }

    companion object {
        /** Matches Okja's pinned Python openWakeWord replay: 80 ms at 16 kHz. */
        const val DEFAULT_INFERENCE_WINDOW_SAMPLES = 1_280
        const val DEFAULT_DEBOUNCE_MS = 2_000
    }
}
