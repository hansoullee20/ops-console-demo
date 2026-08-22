package com.soul.aihub.voice

/**
 * Latches PCM integrity for one command utterance.
 *
 * Once any discontinuity is observed, the utterance remains untrusted until a new utterance
 * explicitly begins. The first live frame is checked against the exact end position of the
 * pre-roll snapshot, closing the pre-roll -> live gap that a frame-only tracker cannot detect.
 * Physical authorization also requires at least one live frame from the current capture epoch;
 * pre-roll alone can never authorize a device action.
 */
class UtteranceAudioIntegrityGate {
    private val continuity = PcmContinuityTracker()
    private var active = false
    private var trusted = false
    private var observedLiveFrame = false

    fun beginUtterance(expectedFirstLiveSampleIndex: Long) {
        require(expectedFirstLiveSampleIndex >= 0L) {
            "expectedFirstLiveSampleIndex must be non-negative"
        }
        continuity.reset(expectedStartSampleIndex = expectedFirstLiveSampleIndex)
        active = true
        trusted = true
        observedLiveFrame = false
    }

    fun observe(frame: PcmFrame): PcmContinuityStatus {
        check(active) { "beginUtterance() must be called before observing PCM" }
        val status = continuity.observe(frame)
        observedLiveFrame = true
        if (!status.continuous) trusted = false
        return status
    }

    /** Physical device authorization must require this to be true. */
    fun canAuthorizeDeviceCommand(): Boolean = active && trusted && observedLiveFrame

    fun endUtterance() {
        active = false
        trusted = false
        observedLiveFrame = false
        continuity.reset()
    }
}
