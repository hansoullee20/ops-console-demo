package com.soul.aihub.voice

/**
 * Latches PCM integrity for one command utterance.
 *
 * Once any discontinuity is observed, the utterance remains untrusted until a
 * new utterance explicitly begins. The first live frame is also checked against
 * the exact end position of the pre-roll snapshot, closing the pre-roll -> live
 * gap that a frame-only continuity tracker cannot detect by itself.
 */
class UtteranceAudioIntegrityGate {
    private val continuity = PcmContinuityTracker()
    private var active = false
    private var trusted = false

    fun beginUtterance(expectedFirstLiveSampleIndex: Long) {
        require(expectedFirstLiveSampleIndex >= 0L) {
            "expectedFirstLiveSampleIndex must be non-negative"
        }
        continuity.reset(expectedStartSampleIndex = expectedFirstLiveSampleIndex)
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
