package com.soul.aihub.voice

/**
 * Canonical Okja microphone frame: 16 kHz, mono, signed PCM16.
 *
 * [sequence] and [startSampleIndex] are capture-order metadata. Consumers must
 * use them to detect gaps caused by backpressure or dropped frames before a
 * transcript is trusted for physical device control.
 */
data class PcmFrame(
    val samples: ShortArray,
    val capturedAtElapsedRealtimeNs: Long,
    val sequence: Long,
    val startSampleIndex: Long,
) {
    init {
        require(sequence >= 0) { "sequence must be non-negative" }
        require(startSampleIndex >= 0) { "startSampleIndex must be non-negative" }
    }

    val endSampleIndexExclusive: Long
        get() = startSampleIndex + samples.size.toLong()
}
