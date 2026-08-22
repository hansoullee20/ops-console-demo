package com.soul.aihub.voice

import kotlinx.coroutines.flow.SharedFlow

/** A contiguous PCM window with capture-position provenance. */
data class PcmWindow(
    val samples: ShortArray,
    val startSampleIndex: Long,
    val endSampleIndexExclusive: Long,
) {
    init {
        require(startSampleIndex >= 0L) { "startSampleIndex must be non-negative" }
        require(endSampleIndexExclusive >= startSampleIndex) {
            "endSampleIndexExclusive must be >= startSampleIndex"
        }
        require(endSampleIndexExclusive - startSampleIndex == samples.size.toLong()) {
            "PCM window range does not match sample count"
        }
    }
}

/**
 * Consumers such as wake-word, VAD, ASR, and diagnostics read PCM from this contract.
 * They must not create or own an AudioRecord themselves.
 */
interface PcmAudioSource {
    val frames: SharedFlow<PcmFrame>

    /** Returns the newest requested duration plus the exact sample range it represents. */
    fun readPreRollWindow(durationMs: Int): PcmWindow

    /** Compatibility helper for diagnostic code that does not authorize physical actions. */
    fun readPreRoll(durationMs: Int): ShortArray = readPreRollWindow(durationMs).samples
}
