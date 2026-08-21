package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WakeBenchmarkHarnessTest {
    private class SequenceDetector(
        private val detectionsBySequence: Map<Long, String>,
    ) : WakeDetector {
        var closed = false

        override fun accept(frame: PcmFrame): WakeDetection? {
            val keyword = detectionsBySequence[frame.sequence] ?: return null
            return WakeDetection(
                keyword = keyword,
                detectedAtElapsedRealtimeNs = frame.capturedAtElapsedRealtimeNs,
                score = 0.9f,
            )
        }

        override fun close() {
            closed = true
        }
    }

    @Test
    fun positiveWakeIsMatchedInSampleTimeAndLatencyIsStable() {
        val detector = SequenceDetector(mapOf(5L to "옥자야"))
        val case = WakeBenchmarkCase(
            id = "positive",
            pcm16 = ShortArray(320 * 10),
            expectedWakes = listOf(
                ExpectedWake(
                    keyword = "옥자야",
                    keywordEndSampleIndex = 1_600L,
                    matchEarlyMs = 0,
                    matchLateMs = 500,
                ),
            ),
        )

        val result = WakeBenchmarkHarness().run(case, "fake", detector)

        assertEquals(1, result.intentionalAttempts)
        assertEquals(1, result.detectedAttempts)
        assertEquals(0, result.misses)
        assertEquals(1.0, result.recall!!, 0.0)
        assertEquals(20.0, result.latenciesMs.single(), 0.001)
        assertEquals(0, result.extraDetectionsDuringPositiveCase)
        assertNull(result.falseActivationsPerHour)
        assertTrue(detector.closed)
    }

    @Test
    fun keywordMismatchDoesNotAuthorizeExpectedWake() {
        val detector = SequenceDetector(mapOf(5L to "옥자"))
        val case = WakeBenchmarkCase(
            id = "mismatch",
            pcm16 = ShortArray(320 * 10),
            expectedWakes = listOf(
                ExpectedWake(
                    keyword = "옥자야",
                    keywordEndSampleIndex = 1_600L,
                ),
            ),
        )

        val result = WakeBenchmarkHarness().run(case, "fake", detector)

        assertEquals(0, result.detectedAttempts)
        assertEquals(1, result.misses)
        assertEquals(1, result.extraDetectionsDuringPositiveCase)
        assertEquals(0.0, result.recall!!, 0.0)
    }

    @Test
    fun negativeCaseReportsFalseActivationsPerHour() {
        val detector = SequenceDetector(
            mapOf(
                10L to "옥자야",
                20L to "옥자야",
            ),
        )
        val case = WakeBenchmarkCase(
            id = "negative-10s",
            pcm16 = ShortArray(16_000 * 10),
        )

        val result = WakeBenchmarkHarness().run(case, "fake", detector)

        assertEquals(0, result.intentionalAttempts)
        assertNull(result.recall)
        assertEquals(2, result.falseActivations)
        assertEquals(0, result.extraDetectionsDuringPositiveCase)
        assertEquals(0.002777777777777778, result.negativeListeningHours, 1e-12)
        assertEquals(720.0, result.falseActivationsPerHour!!, 0.001)
    }

    @Test
    fun aggregateSeparatesPositiveRecallFromNegativeListeningTime() {
        val harness = WakeBenchmarkHarness()
        val positive = harness.run(
            case = WakeBenchmarkCase(
                id = "p",
                pcm16 = ShortArray(320 * 10),
                expectedWakes = listOf(ExpectedWake("옥자야", 1_600L)),
            ),
            detectorName = "fake",
            detector = SequenceDetector(mapOf(5L to "옥자야")),
        )
        val negative = harness.run(
            case = WakeBenchmarkCase(
                id = "n",
                pcm16 = ShortArray(16_000 * 3_600),
            ),
            detectorName = "fake",
            detector = SequenceDetector(mapOf(10L to "옥자야")),
        )

        val aggregate = WakeBenchmarkAggregate.from(listOf(positive, negative))

        assertEquals(2, aggregate.caseCount)
        assertEquals(1, aggregate.intentionalAttempts)
        assertEquals(1, aggregate.detectedAttempts)
        assertEquals(1.0, aggregate.recall!!, 0.0)
        assertEquals(1.0, aggregate.negativeListeningHours, 1e-9)
        assertEquals(1.0, aggregate.falseActivationsPerHour!!, 1e-9)
        assertEquals(20.0, aggregate.latencyP50Ms!!, 0.001)
        assertEquals(20.0, aggregate.latencyP95Ms!!, 0.001)
    }
}
