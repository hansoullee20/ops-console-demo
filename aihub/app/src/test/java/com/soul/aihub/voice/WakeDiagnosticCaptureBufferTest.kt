package com.soul.aihub.voice

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WakeDiagnosticCaptureBufferTest {
    private fun frame(sequence: Long, start: Long, value: Short): PcmFrame {
        return PcmFrame(
            samples = ShortArray(320) { value },
            capturedAtElapsedRealtimeNs = sequence * 20_000_000L,
            sequence = sequence,
            startSampleIndex = start,
        )
    }

    @Test
    fun captureRequiresAnObservedFrame() {
        val capture = WakeDiagnosticCaptureBuffer(
            readPreRoll = { ShortArray(0) },
            postRollMs = 0,
            eventIdFactory = { "unused" },
        )

        assertNull(capture.captureManualMiss("miss-1"))
        assertEquals(0, capture.pendingCount)
    }

    @Test
    fun candidateCopiesExistingPreRollThenAppendsBoundedPostRollExactlyOnce() {
        var preRoll = ShortArray(320) { 1 }
        val capture = WakeDiagnosticCaptureBuffer(
            readPreRoll = { preRoll.copyOf() },
            preRollMs = 20,
            postRollMs = 20,
            eventIdFactory = { "candidate-1" },
        )

        val triggerFrame = frame(0, 0, 1)
        capture.acceptFrame(triggerFrame)
        assertNull(capture.captureCandidate(score = 0.8f, threshold = 0.5f, accepted = true))
        assertEquals(1, capture.pendingCount)

        preRoll = ShortArray(320) { 9 } // must not affect the already-started capture
        val completed = capture.acceptFrame(frame(1, 320, 2))

        assertEquals(1, completed.size)
        val clip = completed.single()
        assertEquals("candidate-1", clip.eventId)
        assertEquals(WakeDiagnosticKind.CANDIDATE, clip.kind)
        assertEquals(0L, clip.clipStartSampleIndex)
        assertEquals(640L, clip.clipEndSampleIndexExclusive)
        assertEquals(320L, clip.triggerSampleIndexExclusive)
        assertEquals(320, clip.preSamplesConfigured)
        assertEquals(320, clip.postSamplesConfigured)
        assertTrue(clip.postRollComplete)
        assertTrue(clip.pcmContinuous)
        assertEquals(0, capture.pendingCount)
        assertArrayEquals(
            ShortArray(640) { index -> if (index < 320) 1 else 2 },
            clip.pcm16,
        )
    }

    @Test
    fun droppedPostRollFrameIsMarkedDiscontinuousInsteadOfHidden() {
        val capture = WakeDiagnosticCaptureBuffer(
            readPreRoll = { ShortArray(320) { 1 } },
            preRollMs = 20,
            postRollMs = 20,
            eventIdFactory = { "candidate-gap" },
        )

        capture.acceptFrame(frame(0, 0, 1))
        capture.captureCandidate(score = 0.7f, threshold = 0.5f, accepted = true)

        val completed = capture.acceptFrame(frame(2, 640, 3))

        assertEquals(1, completed.size)
        assertFalse(completed.single().pcmContinuous)
        assertTrue(completed.single().postRollComplete)
    }

    @Test
    fun flushPreservesPartialEvidenceButMarksPostRollIncomplete() {
        val capture = WakeDiagnosticCaptureBuffer(
            readPreRoll = { ShortArray(320) { 4 } },
            preRollMs = 20,
            postRollMs = 40,
            eventIdFactory = { "manual-1" },
        )

        capture.acceptFrame(frame(0, 0, 4))
        capture.captureManualMiss()
        capture.acceptFrame(frame(1, 320, 5))

        val flushed = capture.flushPending()

        assertEquals(1, flushed.size)
        val clip = flushed.single()
        assertEquals(WakeDiagnosticKind.MANUAL_MISS, clip.kind)
        assertFalse(clip.postRollComplete)
        assertTrue(clip.pcmContinuous)
        assertEquals(640, clip.pcm16.size)
        assertEquals(0, capture.pendingCount)
    }

    @Test
    fun zeroPostRollReturnsCompletedClipImmediately() {
        val capture = WakeDiagnosticCaptureBuffer(
            readPreRoll = { ShortArray(320) { 7 } },
            preRollMs = 20,
            postRollMs = 0,
            eventIdFactory = { "instant" },
        )

        capture.acceptFrame(frame(0, 0, 7))
        val clip = capture.captureCandidate(score = 0.9f, threshold = 0.5f, accepted = true)

        requireNotNull(clip)
        assertTrue(clip.postRollComplete)
        assertTrue(clip.pcmContinuous)
        assertEquals(320, clip.pcm16.size)
    }
}
