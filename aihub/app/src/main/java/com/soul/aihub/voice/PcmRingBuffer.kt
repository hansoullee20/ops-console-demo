package com.soul.aihub.voice

/**
 * Thread-safe circular PCM16 buffer. Capacity is intentionally larger than the
 * pre-roll window so wake/ASR experiments can vary pre-roll without changing
 * microphone ownership or capture topology.
 *
 * The buffer also tracks the absolute sample range for the current AudioEngine
 * capture epoch. AudioEngine clears the ring before every new microphone start.
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
    private var totalSamplesWritten = 0L

    @Synchronized
    fun append(samples: ShortArray, length: Int = samples.size) {
        require(length in 0..samples.size)
        if (length == 0) return
        check(totalSamplesWritten <= Long.MAX_VALUE - length.toLong()) {
            "PCM sample position overflow"
        }

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
        totalSamplesWritten += length.toLong()
    }

    @Synchronized
    fun snapshotLatestWindow(durationMs: Int): PcmWindow {
        require(durationMs >= 0)
        val requested = (sampleRateHz.toLong() * durationMs / 1000L)
            .coerceAtMost(Int.MAX_VALUE.toLong())
            .toInt()
        val outSize = if (durationMs == 0 || count == 0) 0 else minOf(requested, count)
        val out = ShortArray(outSize)

        if (outSize > 0) {
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
        }

        val end = totalSamplesWritten
        return PcmWindow(
            samples = out,
            startSampleIndex = end - outSize.toLong(),
            endSampleIndexExclusive = end,
        )
    }

    @Synchronized
    fun snapshotLatest(durationMs: Int): ShortArray = snapshotLatestWindow(durationMs).samples

    @Synchronized
    fun clear() {
        writeIndex = 0
        count = 0
        totalSamplesWritten = 0L
    }

    @Synchronized
    fun bufferedSamples(): Int = count

    @Synchronized
    fun endSampleIndexExclusive(): Long = totalSamplesWritten

    fun capacitySamples(): Int = capacitySamples
}
