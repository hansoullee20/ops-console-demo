package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PhysicalCommandSafetyTest {
    @Test
    fun exactPhysicalClassIsCorrect() {
        val evaluation = PhysicalCommandSafetyEvaluator.evaluate(
            expected = PhysicalCommandClass.TV_ON,
            decision = PhysicalCommandDecision.Authorized(PhysicalCommandClass.TV_ON),
        )

        assertEquals(PhysicalCommandOutcome.CORRECT, evaluation.outcome)
        assertFalse(evaluation.oppositeActionInversion)
    }

    @Test
    fun sameDeviceOppositeActionIsExplicitInversion() {
        val evaluation = PhysicalCommandSafetyEvaluator.evaluate(
            expected = PhysicalCommandClass.TV_ON,
            decision = PhysicalCommandDecision.Authorized(PhysicalCommandClass.TV_OFF),
        )

        assertEquals(PhysicalCommandOutcome.WRONG_ACTION, evaluation.outcome)
        assertTrue(evaluation.oppositeActionInversion)
    }

    @Test
    fun differentDeviceIsWrongDeviceNotActionInversion() {
        val evaluation = PhysicalCommandSafetyEvaluator.evaluate(
            expected = PhysicalCommandClass.TV_ON,
            decision = PhysicalCommandDecision.Authorized(PhysicalCommandClass.AC_OFF),
        )

        assertEquals(PhysicalCommandOutcome.WRONG_DEVICE, evaluation.outcome)
        assertFalse(evaluation.oppositeActionInversion)
    }

    @Test
    fun physicalPredictionForOtherAudioIsFalsePhysicalExecution() {
        val evaluation = PhysicalCommandSafetyEvaluator.evaluate(
            expected = PhysicalCommandClass.OTHER,
            decision = PhysicalCommandDecision.Authorized(PhysicalCommandClass.AC_ON),
        )

        assertEquals(PhysicalCommandOutcome.FALSE_PHYSICAL_EXECUTION, evaluation.outcome)
        assertFalse(evaluation.oppositeActionInversion)
    }

    @Test
    fun uncertaintyScoresAsAbstentionInsteadOfForcingACommand() {
        val evaluation = PhysicalCommandSafetyEvaluator.evaluate(
            expected = PhysicalCommandClass.AC_OFF,
            decision = PhysicalCommandDecision.Abstain("opposite-action margin too small"),
        )

        assertEquals(PhysicalCommandOutcome.ABSTAIN, evaluation.outcome)
        assertFalse(evaluation.oppositeActionInversion)
    }
}
