package com.soul.aihub.voice

import kotlinx.coroutines.flow.SharedFlow

/**
 * Consumers such as wake-word, VAD, ASR, and diagnostics read PCM from this contract.
 * They must not create or own an AudioRecord themselves.
 */
interface PcmAudioSource {
    val frames: SharedFlow<PcmFrame>

    /** Returns the newest requested duration from the local ring buffer. */
    fun readPreRoll(durationMs: Int): ShortArray
}
