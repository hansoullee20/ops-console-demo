package com.soul.aihub.voice

/** Result of validating one PCM frame against the previously observed frame. */
data class PcmContinuityStatus(
    val continuous: Boolean,
    val expectedSequence: Long?,
    val actualSequence: Long,
    val expectedStartSampleIndex: Long?,
    val actualStartSampleIndex: Long,
    val missingFrames: Long,
    val missingSamples: Long,
)

/**
 * Consumer-side continuity guard for the shared PCM stream.
 *
 * AudioEngine intentionally uses bounded fan-out. If a consumer falls behind,
 * frames may be dropped for that consumer. Sequence/sample metadata lets the
 * consumer detect that loss and fail closed instead of trusting an incomplete
 * utterance for a physical device command.
 */
class PcmContinuityTracker {
    private var nextSequence: Long? = null
    private var nextSampleIndex: Long? = null

    fun observe(frame: PcmFrame): PcmContinuityStatus {
        val expectedSequence = nextSequence
        val expectedStartSampleIndex = nextSampleIndex
        val continuous = expectedSequence == null ||
            (frame.sequence == expectedSequence && frame.startSampleIndex == expectedStartSampleIndex)

        val missingFrames = if (expectedSequence == null) {
            0L
        } else {
            maxOf(0L, frame.sequence - expectedSequence)
        }
        val missingSamples = if (expectedStartSampleIndex == null) {
            0L
        } else {
            maxOf(0L, frame.startSampleIndex - expectedStartSampleIndex)
        }

        nextSequence = frame.sequence + 1L
        nextSampleIndex = frame.endSampleIndexExclusive

        return PcmContinuityStatus(
            continuous = continuous,
            expectedSequence = expectedSequence,
            actualSequence = frame.sequence,
            expectedStartSampleIndex = expectedStartSampleIndex,
            actualStartSampleIndex = frame.startSampleIndex,
            missingFrames = missingFrames,
            missingSamples = missingSamples,
        )
    }

    fun reset() {
        nextSequence = null
        nextSampleIndex = null
    }
}
