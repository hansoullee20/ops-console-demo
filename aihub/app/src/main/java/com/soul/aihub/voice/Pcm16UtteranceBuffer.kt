package com.soul.aihub.voice

/**
 * Bounded in-memory PCM16 accumulator for utterance-scoped offline/simulated-streaming ASR.
 *
 * It deliberately throws on overflow rather than silently truncating speech, because a
 * truncated utterance must never be mistaken for complete command audio.
 */
class Pcm16UtteranceBuffer(
    private val maxSamples: Int,
) {
    init {
        require(maxSamples > 0) { "maxSamples must be positive" }
    }

    private var data = ShortArray(minOf(maxSamples, 16_000))
    private var size = 0

    fun begin(preRollPcm16: ShortArray) {
        reset()
        append(preRollPcm16)
    }

    fun append(samples: ShortArray) {
        if (samples.isEmpty()) return
        require(size + samples.size <= maxSamples) {
            "utterance exceeds bounded PCM capacity: ${size + samples.size} > $maxSamples samples"
        }
        ensureCapacity(size + samples.size)
        samples.copyInto(data, destinationOffset = size)
        size += samples.size
    }

    fun snapshot(): ShortArray = data.copyOf(size)

    fun sampleCount(): Int = size

    fun reset() {
        size = 0
    }

    private fun ensureCapacity(required: Int) {
        if (required <= data.size) return
        var next = maxOf(1, data.size)
        while (next < required) {
            next = minOf(maxSamples, next * 2)
            if (next == data.size) break
        }
        require(next >= required) { "unable to grow PCM buffer to $required samples" }
        data = data.copyOf(next)
    }
}
