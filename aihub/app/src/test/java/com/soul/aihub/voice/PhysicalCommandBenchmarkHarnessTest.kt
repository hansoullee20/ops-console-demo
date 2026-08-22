package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PhysicalCommandBenchmarkHarnessTest {
    private class FakeAuthorizer(
        private val decision: PhysicalCommandDecision,
    ) : PhysicalCommandAuthorizer {
        var beginSamples = 0
        val sequences = mutableListOf<Long>()

        override fun reset() {
            sequences.clear()
        }

        override fun begin(preRollPcm16: ShortArray) {
            beginSamples = preRollPcm16.size
        }

        override fun accept(frame: PcmFrame) {
            sequences += frame.sequence
        }

        override fun finish(): PhysicalCommandDecision = decision
    }

    @Test
    fun replaysSamePcmAndScoresCorrectPhysicalCommand() {
        val authorizer = FakeAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.TV_ON),
        )
        val case = RecordedPhysicalCommandCase(
            id = "tv-on-01",
            pcm16 = ShortArray(960) { it.toShort() },
            expected = PhysicalCommandClass.TV_ON,
            preRollSamples = 320,
        )

        val result = PhysicalCommandBenchmarkHarness().run(
            case = case,
            engineName = "fake",
            authorizer = authorizer,
        )

        assertEquals(320, authorizer.beginSamples)
        assertEquals(listOf(0L, 1L), authorizer.sequences)
        assertEquals(PhysicalCommandOutcome.CORRECT, result.outcome)
        assertFalse(result.oppositeActionInversion)
        assertFalse(result.discontinuityDetected)
    }

    @Test
    fun reportsOppositeActionAsReleaseBlockingInversion() {
        val authorizer = FakeAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.AC_ON),
        )
        val case = RecordedPhysicalCommandCase(
            id = "ac-off-01",
            pcm16 = ShortArray(640),
            expected = PhysicalCommandClass.AC_OFF,
        )

        val result = PhysicalCommandBenchmarkHarness().run(case, "fake", authorizer)

        assertEquals(PhysicalCommandOutcome.WRONG_ACTION, result.outcome)
        assertTrue(result.oppositeActionInversion)
    }

    @Test
    fun otherAudioAcceptedAsCommandIsFalsePhysicalExecution() {
        val authorizer = FakeAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.TV_OFF),
        )
        val case = RecordedPhysicalCommandCase(
            id = "background-tv-01",
            pcm16 = ShortArray(320),
            expected = PhysicalCommandClass.OTHER,
        )

        val result = PhysicalCommandBenchmarkHarness().run(case, "fake", authorizer)

        assertEquals(PhysicalCommandOutcome.FALSE_PHYSICAL_EXECUTION, result.outcome)
        assertFalse(result.oppositeActionInversion)
    }
}
