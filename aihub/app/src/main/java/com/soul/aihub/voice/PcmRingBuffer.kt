package com.soul.aihub.voice

/**
 * Thread-safe circular PCM16 buffer. Capacity is intentionally larger than the
 * pre-roll window so wake/ASR experiments can vary pre-roll without changing
 * microphone ownership or capture topology.
 */
class PcmRingBuffer(
    private val sampleRateHz: Int,
    capacityMs: Int,
) {
    init {
        require(sampleRateHz > 0)
        require(capacityMs > 0)
    }

    private val capacitySamples = (sampleRateHz.toLong() * capacityMs / 1000L)
        .coerceAtLeast(1L)
        .coerceAtMost(Int.MAX_VALUE.toLong())
        .toInt()
    private val data = ShortArray(capacitySamples)
    private var writeIndex = 0
    private var count = 0

    @Synchronized
    fun append(samples: ShortArray, length: Int = samples.size) {
        require(length in 0..samples.size)
        if (length == 0) return

        var src = 0
        var remaining = length
        while (remaining > 0) {
            val chunk = minOf(remaining, capacitySamples - writeIndex)
            samples.copyInto(data, writeIndex, src, src + chunk)
            writeIndex = (writeIndex + chunk) % capacitySamples
            src += chunk
            remaining -= chunk
        }
        count = minOf(capacitySamples, count + length)
    }

    @Synchronized
    fun snapshotLatest(durationMs: Int): ShortArray {
        require(durationMs >= 0)
        if (durationMs == 0 || count == 0) return ShortArray(0)

        val requested = (sampleRateHz.toLong() * durationMs / 1000L)
            .coerceAtMost(Int.MAX_VALUE.toLong())
            .toInt()
        val outSize = minOf(requested, count)
        val out = ShortArray(outSize)
        var readIndex = (writeIndex - outSize + capacitySamples) % capacitySamples
        var dst = 0
        var remaining = outSize
        while (remaining > 0) {
            val chunk = minOf(remaining, capacitySamples - readIndex)
            data.copyInto(out, dst, readIndex, readIndex + chunk)
            readIndex = (readIndex + chunk) % capacitySamples
            dst += chunk
            remaining -= chunk
        }
        return out
    }

    @Synchronized
    fun bufferedSamples(): Int = count

    fun capacitySamples(): Int = capacitySamples
}
