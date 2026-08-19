package com.soul.aihub.voice

/**
 * Latches PCM integrity for one command utterance.
 *
 * Once any discontinuity is observed, the utterance remains untrusted until a
 * new utterance explicitly begins. This prevents later contiguous frames from
 * accidentally re-authorizing a transcript whose earlier audio was incomplete.
 */
class UtteranceAudioIntegrityGate {
    private val continuity = PcmContinuityTracker()
    private var active = false
    private var trusted = false

    fun beginUtterance() {
        continuity.reset()
        active = true
        trusted = true
    }

    fun observe(frame: PcmFrame): PcmContinuityStatus {
        check(active) { "beginUtterance() must be called before observing PCM" }
        val status = continuity.observe(frame)
        if (!status.continuous) trusted = false
        return status
    }

    /** Physical device authorization must require this to be true. */
    fun canAuthorizeDeviceCommand(): Boolean = active && trusted

    fun endUtterance() {
        active = false
        trusted = false
        continuity.reset()
    }
}
