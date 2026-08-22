package com.soul.aihub.voice

import java.util.UUID

/** Why a diagnostic clip was requested. */
enum class WakeDiagnosticKind {
    CANDIDATE,
    MANUAL_MISS,
}

/**
 * Completed in-memory diagnostic capture.
 *
 * This type deliberately performs no filesystem I/O. A diagnostic/debug surface may
 * persist the clip only when the product's benchmark-consent/retention policy allows
 * it. Production voice code can therefore reuse this component without silently
 * turning the always-listening ring buffer into stored audio.
 */
data class WakeDiagnosticClip(
    val eventId: String,
    val kind: WakeDiagnosticKind,
    val pcm16: ShortArray,
    val sampleRateHz: Int,
    val triggerSampleIndexExclusive: Long,
    val clipStartSampleIndex: Long,
    val clipEndSampleIndexExclusive: Long,
    val preSamplesConfigured: Int,
    val postSamplesConfigured: Int,
    val score: Float?,
    val threshold: Float?,
    val accepted: Boolean?,
    val postRollComplete: Boolean,
    val pcmContinuous: Boolean,
)

/**
 * Privacy-first candidate/manual-miss capture buffer for the single-owner PCM path.
 *
 * The caller supplies AudioEngine's existing pre-roll reader and forwards PcmFrames.
 * This class never opens AudioRecord and never keeps a second continuous PCM ring.
 * A capture copies the current AudioEngine pre-roll once, then appends only the bounded
 * post-roll frames needed for that event.
 *
 * Call order for detector candidates:
 *
 *  1. AudioEngine emits frame (its ring already contains that frame).
 *  2. [acceptFrame] forwards the frame here.
 *  3. Wake detector evaluates the same frame.
 *  4. On candidate, call [captureCandidate].
 *
 * That order ensures the trigger frame is present exactly once in the pre-roll copy.
 */
class WakeDiagnosticCaptureBuffer(
    private val readPreRoll: (durationMs: Int) -> ShortArray,
    private val sampleRateHz: Int = 16_000,
    private val preRollMs: Int = 3_000,
    private val postRollMs: Int = 2_000,
    private val eventIdFactory: () -> String = { "diag-${UUID.randomUUID()}" },
) {
    init {
        require(sampleRateHz > 0) { "sampleRateHz must be positive" }
        require(preRollMs > 0) { "preRollMs must be positive" }
        require(postRollMs >= 0) { "postRollMs must be non-negative" }
    }

    private val preSamplesConfigured = millisecondsToSamples(preRollMs)
    private val postSamplesConfigured = millisecondsToSamples(postRollMs)
    private val pending = mutableListOf<PendingCapture>()
    private var lastObservedEndSampleIndex: Long? = null

    val pendingCount: Int
        @Synchronized get() = pending.size

    /**
     * Forward each shared PCM frame here. Any captures completed by this frame are
     * returned to the caller for optional consent-gated persistence.
     */
    @Synchronized
    fun acceptFrame(frame: PcmFrame): List<WakeDiagnosticClip> {
        val completed = mutableListOf<WakeDiagnosticClip>()

        val iterator = pending.iterator()
        while (iterator.hasNext()) {
            val capture = iterator.next()
            if (capture.remainingPostSamples > 0) {
                if (frame.startSampleIndex != capture.nextExpectedSampleIndex) {
                    capture.pcmContinuous = false
                }
                val take = minOf(capture.remainingPostSamples, frame.samples.size)
                capture.append(frame.samples, take)
                capture.remainingPostSamples -= take
                capture.nextExpectedSampleIndex = frame.startSampleIndex + take.toLong()
            }

            if (capture.remainingPostSamples == 0) {
                completed += capture.finish(postRollComplete = true)
                iterator.remove()
            }
        }

        lastObservedEndSampleIndex = frame.endSampleIndexExclusive
        return completed
    }

    @Synchronized
    fun captureCandidate(
        score: Float,
        threshold: Float,
        accepted: Boolean,
        eventId: String = eventIdFactory(),
    ): WakeDiagnosticClip? {
        require(score.isFinite()) { "score must be finite" }
        require(threshold.isFinite()) { "threshold must be finite" }
        return startCapture(
            eventId = eventId,
            kind = WakeDiagnosticKind.CANDIDATE,
            score = score,
            threshold = threshold,
            accepted = accepted,
        )
    }

    @Synchronized
    fun captureManualMiss(eventId: String = eventIdFactory()): WakeDiagnosticClip? {
        return startCapture(
            eventId = eventId,
            kind = WakeDiagnosticKind.MANUAL_MISS,
            score = null,
            threshold = null,
            accepted = null,
        )
    }

    /** Finalize incomplete post-roll when a diagnostic/capture session stops. */
    @Synchronized
    fun flushPending(): List<WakeDiagnosticClip> {
        val completed = pending.map { it.finish(postRollComplete = false) }
        pending.clear()
        return completed
    }

    private fun startCapture(
        eventId: String,
        kind: WakeDiagnosticKind,
        score: Float?,
        threshold: Float?,
        accepted: Boolean?,
    ): WakeDiagnosticClip? {
        require(eventId.isNotBlank()) { "eventId must not be blank" }
        val triggerEnd = lastObservedEndSampleIndex ?: return null
        val preRoll = readPreRoll(preRollMs)
        require(preRoll.size <= preSamplesConfigured) {
            "pre-roll reader returned ${preRoll.size} samples, expected <= $preSamplesConfigured"
        }

        val capture = PendingCapture(
            eventId = eventId,
            kind = kind,
            preRoll = preRoll,
            triggerSampleIndexExclusive = triggerEnd,
            postSamplesConfigured = postSamplesConfigured,
            sampleRateHz = sampleRateHz,
            preSamplesConfigured = preSamplesConfigured,
            score = score,
            threshold = threshold,
            accepted = accepted,
        )

        return if (postSamplesConfigured == 0) {
            capture.finish(postRollComplete = true)
        } else {
            pending += capture
            null
        }
    }

    private fun millisecondsToSamples(ms: Int): Int {
        return (sampleRateHz.toLong() * ms.toLong() / 1_000L)
            .coerceAtMost(Int.MAX_VALUE.toLong())
            .toInt()
    }

    private class PendingCapture(
        val eventId: String,
        val kind: WakeDiagnosticKind,
        preRoll: ShortArray,
        val triggerSampleIndexExclusive: Long,
        val postSamplesConfigured: Int,
        val sampleRateHz: Int,
        val preSamplesConfigured: Int,
        val score: Float?,
        val threshold: Float?,
        val accepted: Boolean?,
    ) {
        private val data = ShortArray(preRoll.size + postSamplesConfigured)
        private var size = preRoll.size
        var remainingPostSamples = postSamplesConfigured
        var nextExpectedSampleIndex = triggerSampleIndexExclusive
        var pcmContinuous = true

        init {
            preRoll.copyInto(data)
        }

        fun append(samples: ShortArray, length: Int) {
            require(length in 0..samples.size)
            if (length == 0) return
            samples.copyInto(data, destinationOffset = size, startIndex = 0, endIndex = length)
            size += length
        }

        fun finish(postRollComplete: Boolean): WakeDiagnosticClip {
            val pcm = data.copyOf(size)
            val clipStart = maxOf(0L, triggerSampleIndexExclusive - (size - (postSamplesConfigured - remainingPostSamples)).toLong())
            val clipEnd = clipStart + pcm.size.toLong()
            return WakeDiagnosticClip(
                eventId = eventId,
                kind = kind,
                pcm16 = pcm,
                sampleRateHz = sampleRateHz,
                triggerSampleIndexExclusive = triggerSampleIndexExclusive,
                clipStartSampleIndex = clipStart,
                clipEndSampleIndexExclusive = clipEnd,
                preSamplesConfigured = preSamplesConfigured,
                postSamplesConfigured = postSamplesConfigured,
                score = score,
                threshold = threshold,
                accepted = accepted,
                postRollComplete = postRollComplete,
                pcmContinuous = pcmContinuous,
            )
        }
    }
}
