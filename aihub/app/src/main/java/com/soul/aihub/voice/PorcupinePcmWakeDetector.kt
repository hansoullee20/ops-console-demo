package com.soul.aihub.voice

import android.content.Context
import ai.picovoice.porcupine.Porcupine

/**
 * Low-level Picovoice Porcupine adapter for Okja's caller-owned PCM stream.
 *
 * This class deliberately uses Porcupine.process(short[]) rather than PorcupineManager, so
 * AudioEngine remains the only AudioRecord owner. Input discontinuities rebuild Porcupine before
 * processing the first post-gap frame so internal wake context is never carried across missing PCM.
 */
class PorcupinePcmWakeDetector private constructor(
    private val context: Context,
    private val accessKey: String,
    private val keywordPath: String,
    private val keyword: String,
    private val sensitivity: Float,
) : WakeDetector {
    private val continuity = PcmContinuityTracker()
    private var porcupine: Porcupine = buildEngine()
    private var accumulator = FixedPcmFrameAccumulator(porcupine.frameLength)
    private var closed = false

    val engineVersion: String
        get() = porcupine.version

    val requiredFrameSamples: Int
        get() = porcupine.frameLength

    override fun accept(frame: PcmFrame): WakeDetection? {
        check(!closed) { "detector is closed" }

        val status = continuity.observe(frame)
        if (!status.continuous) {
            rebuildAfterDiscontinuity()
        }

        var firstDetection: WakeDetection? = null
        accumulator.accept(frame.samples) { porcupineFrame ->
            val keywordIndex = porcupine.process(porcupineFrame)
            if (keywordIndex >= 0 && firstDetection == null) {
                firstDetection = WakeDetection(
                    keyword = keyword,
                    detectedAtElapsedRealtimeNs = frame.capturedAtElapsedRealtimeNs,
                    score = null,
                )
            }
        }
        return firstDetection
    }

    override fun close() {
        if (closed) return
        closed = true
        accumulator.reset()
        continuity.reset()
        porcupine.delete()
    }

    private fun rebuildAfterDiscontinuity() {
        accumulator.reset()
        try {
            porcupine.delete()
        } finally {
            porcupine = buildEngine()
            accumulator = FixedPcmFrameAccumulator(porcupine.frameLength)
        }
    }

    private fun buildEngine(): Porcupine {
        val engine = Porcupine.Builder()
            .setAccessKey(accessKey)
            .setKeywordPath(keywordPath)
            .setSensitivity(sensitivity)
            .build(context.applicationContext)
        check(engine.sampleRate == AudioEngine.SAMPLE_RATE_HZ) {
            "Porcupine sample rate ${engine.sampleRate} does not match AudioEngine ${AudioEngine.SAMPLE_RATE_HZ}"
        }
        return engine
    }

    companion object {
        fun create(
            context: Context,
            accessKey: String,
            keywordPath: String,
            keyword: String = "옥자야",
            sensitivity: Float = 0.5f,
        ): PorcupinePcmWakeDetector {
            require(accessKey.isNotBlank()) { "Picovoice AccessKey must not be blank" }
            require(keywordPath.isNotBlank()) { "Porcupine keyword path must not be blank" }
            require(keyword.isNotBlank()) { "keyword must not be blank" }
            require(sensitivity in 0f..1f) { "sensitivity must be in [0, 1]" }
            return PorcupinePcmWakeDetector(
                context = context.applicationContext,
                accessKey = accessKey,
                keywordPath = keywordPath,
                keyword = keyword,
                sensitivity = sensitivity,
            )
        }
    }
}

/** Adapts AudioEngine's 320-sample frames to an inference engine's exact frame length. */
internal class FixedPcmFrameAccumulator(
    private val frameSamples: Int,
) {
    private val buffer = ShortArray(frameSamples)
    private var size = 0

    init {
        require(frameSamples > 0) { "frameSamples must be positive" }
    }

    fun accept(samples: ShortArray, onFrame: (ShortArray) -> Unit) {
        var offset = 0
        while (offset < samples.size) {
            val writable = frameSamples - size
            val count = minOf(writable, samples.size - offset)
            samples.copyInto(
                destination = buffer,
                destinationOffset = size,
                startIndex = offset,
                endIndex = offset + count,
            )
            size += count
            offset += count
            if (size == frameSamples) {
                onFrame(buffer.copyOf())
                size = 0
            }
        }
    }

    fun reset() {
        size = 0
    }

    fun pendingSamples(): Int = size
}
