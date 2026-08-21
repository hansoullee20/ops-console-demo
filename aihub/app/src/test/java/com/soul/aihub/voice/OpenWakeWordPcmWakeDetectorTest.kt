package com.soul.aihub.voice

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OpenWakeWordPcmWakeDetectorTest {
    private class FakePredictor(
        private val scores: MutableList<Float>,
    ) : OpenWakeWordFramePredictor {
        override val modelName: String = "okja-test"
        val windows = mutableListOf<ShortArray>()
        var resetCount = 0
        var closed = false

        override fun predict(pcm16: ShortArray): Float {
            windows += pcm16.copyOf()
            return if (scores.isEmpty()) 0.0f else scores.removeAt(0)
        }

        override fun reset() {
            resetCount += 1
        }

        override fun close() {
            closed = true
        }
    }

    private fun frame(sequence: Long, start: Long, value: Short): PcmFrame {
        return PcmFrame(
            samples = ShortArray(320) { value },
            capturedAtElapsedRealtimeNs = sequence * 20_000_000L,
            sequence = sequence,
            startSampleIndex = start,
        )
    }

    @Test
    fun fourAudioEngineFramesBecomeOneExactOpenWakeWordWindow() {
        val predictor = FakePredictor(mutableListOf(0.9f))
        val detector = OpenWakeWordPcmWakeDetector(predictor = predictor, threshold = 0.5f)

        assertNull(detector.accept(frame(0, 0, 1)))
        assertNull(detector.accept(frame(1, 320, 2)))
        assertNull(detector.accept(frame(2, 640, 3)))
        val detection = detector.accept(frame(3, 960, 4))

        requireNotNull(detection)
        assertEquals("옥자야", detection.keyword)
        assertEquals(0.9f, detection.score!!, 0.0f)
        assertEquals(1, predictor.windows.size)
        assertArrayEquals(
            ShortArray(1_280) { index ->
                when (index / 320) {
                    0 -> 1
                    1 -> 2
                    2 -> 3
                    else -> 4
                }
            },
            predictor.windows.single(),
        )
    }

    @Test
    fun belowThresholdProducesNoWake() {
        val predictor = FakePredictor(mutableListOf(0.49f))
        val detector = OpenWakeWordPcmWakeDetector(predictor = predictor, threshold = 0.5f)

        repeat(4) { index ->
            assertNull(detector.accept(frame(index.toLong(), index * 320L, 1)))
        }

        assertEquals(1, predictor.windows.size)
    }

    @Test
    fun debounceUsesPcmSampleTimeRatherThanWallClock() {
        val predictor = FakePredictor(MutableList(30) { 0.9f })
        val detector = OpenWakeWordPcmWakeDetector(
            predictor = predictor,
            threshold = 0.5f,
            debounceMs = 2_000,
        )

        val detections = mutableListOf<Long>()
        repeat(104) { index ->
            detector.accept(frame(index.toLong(), index * 320L, 1))?.let {
                detections += (index + 1L) * 320L
            }
        }

        // First 80 ms window detects at sample 1280. The next accepted detection is
        // exactly 2000 ms / 32000 samples later.
        assertEquals(listOf(1_280L, 33_280L), detections)
    }

    @Test
    fun discontinuityDropsPartialWindowAndResetsHiddenPredictorHistory() {
        val predictor = FakePredictor(mutableListOf(0.9f))
        val detector = OpenWakeWordPcmWakeDetector(predictor = predictor, threshold = 0.5f)

        detector.accept(frame(0, 0, 1))
        detector.accept(frame(1, 320, 1))

        // Missing samples 640..959. Both the local 80 ms buffer and the predictor's
        // hidden streaming feature state must be reset.
        assertNull(detector.accept(frame(3, 960, 2)))
        assertEquals(1, predictor.resetCount)
        assertNull(detector.accept(frame(4, 1_280, 2)))
        assertNull(detector.accept(frame(5, 1_600, 2)))
        val detection = detector.accept(frame(6, 1_920, 2))

        requireNotNull(detection)
        assertEquals(1, predictor.windows.size)
        assertArrayEquals(ShortArray(1_280) { 2 }, predictor.windows.single())
    }

    @Test
    fun sequenceOnlyDiscontinuityAlsoResetsPredictorHistory() {
        val predictor = FakePredictor(mutableListOf(0.9f))
        val detector = OpenWakeWordPcmWakeDetector(predictor = predictor, threshold = 0.5f)

        detector.accept(frame(0, 0, 1))
        detector.accept(frame(1, 320, 1))

        // Sample positions look contiguous, but frame sequence 2 is missing. The shared
        // PCM contract treats either metadata discontinuity as untrusted.
        assertNull(detector.accept(frame(3, 640, 2)))
        assertEquals(1, predictor.resetCount)
        assertNull(detector.accept(frame(4, 960, 2)))
        assertNull(detector.accept(frame(5, 1_280, 2)))
        val detection = detector.accept(frame(6, 1_600, 2))

        requireNotNull(detection)
        assertEquals(1, predictor.windows.size)
        assertArrayEquals(ShortArray(1_280) { 2 }, predictor.windows.single())
    }

    @Test
    fun resetClearsPartialWindowDebounceAndPredictorState() {
        val predictor = FakePredictor(mutableListOf(0.9f, 0.9f))
        val detector = OpenWakeWordPcmWakeDetector(predictor = predictor, threshold = 0.5f)

        detector.accept(frame(0, 0, 1))
        detector.accept(frame(1, 320, 1))
        detector.reset()
        assertEquals(1, predictor.resetCount)

        repeat(3) { index ->
            assertNull(detector.accept(frame((10 + index).toLong(), 3_200L + index * 320L, 2)))
        }
        val firstAfterReset = detector.accept(frame(13, 4_160, 2))
        requireNotNull(firstAfterReset)

        detector.reset()
        assertEquals(2, predictor.resetCount)
        repeat(3) { index ->
            assertNull(detector.accept(frame((20 + index).toLong(), 6_400L + index * 320L, 3)))
        }
        val secondAfterReset = detector.accept(frame(23, 7_360, 3))
        requireNotNull(secondAfterReset)

        assertEquals(2, predictor.windows.size)
    }

    @Test
    fun closeClosesPredictorAndIsIdempotent() {
        val predictor = FakePredictor(mutableListOf())
        val detector = OpenWakeWordPcmWakeDetector(predictor = predictor)

        assertFalse(predictor.closed)
        detector.close()
        detector.close()
        assertTrue(predictor.closed)
    }

    @Test(expected = IllegalArgumentException::class)
    fun predictorScoreOutsideProbabilityRangeFailsClosed() {
        val predictor = FakePredictor(mutableListOf(1.1f))
        val detector = OpenWakeWordPcmWakeDetector(predictor = predictor)

        repeat(4) { index ->
            detector.accept(frame(index.toLong(), index * 320L, 1))
        }
    }
}
