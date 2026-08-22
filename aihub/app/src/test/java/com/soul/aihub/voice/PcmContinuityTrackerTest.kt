package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PcmContinuityTrackerTest {
    private fun frame(sequence: Long, startSampleIndex: Long, samples: Int = 320): PcmFrame {
        return PcmFrame(
            samples = ShortArray(samples),
            capturedAtElapsedRealtimeNs = sequence * 20_000_000L,
            sequence = sequence,
            startSampleIndex = startSampleIndex,
        )
    }

    @Test
    fun contiguousFramesRemainTrusted() {
        val tracker = PcmContinuityTracker()
        val first = tracker.observe(frame(0, 0))
        assertTrue(first.continuous)
        assertNull(first.expectedSequence)

        val second = tracker.observe(frame(1, 320))
        assertTrue(second.continuous)
        assertEquals(0L, second.missingFrames)
        assertEquals(0L, second.missingSamples)
    }

    @Test
    fun droppedFrameIsDetectedBySequenceAndSampleGap() {
        val tracker = PcmContinuityTracker()
        tracker.observe(frame(0, 0))
        val status = tracker.observe(frame(2, 640))

        assertFalse(status.continuous)
        assertEquals(1L, status.expectedSequence)
        assertEquals(320L, status.expectedStartSampleIndex)
        assertEquals(1L, status.missingFrames)
        assertEquals(320L, status.missingSamples)
    }

    @Test
    fun outOfOrderFrameIsAlsoUntrusted() {
        val tracker = PcmContinuityTracker()
        tracker.observe(frame(3, 960))
        val status = tracker.observe(frame(2, 640))

        assertFalse(status.continuous)
        assertEquals(0L, status.missingFrames)
        assertEquals(0L, status.missingSamples)
    }

    @Test
    fun resetStartsANewContinuityEpoch() {
        val tracker = PcmContinuityTracker()
        tracker.observe(frame(5, 1600))
        tracker.reset()
        val status = tracker.observe(frame(100, 32_000))

        assertTrue(status.continuous)
        assertNull(status.expectedSequence)
        assertNull(status.expectedStartSampleIndex)
    }

    @Test
    fun seededSampleBoundaryDetectsGapBeforeFirstLiveFrame() {
        val tracker = PcmContinuityTracker()
        tracker.reset(expectedStartSampleIndex = 3_200L)

        val status = tracker.observe(frame(10, 3_520L))

        assertFalse(status.continuous)
        assertNull(status.expectedSequence)
        assertEquals(3_200L, status.expectedStartSampleIndex)
        assertEquals(320L, status.missingSamples)
    }
}
