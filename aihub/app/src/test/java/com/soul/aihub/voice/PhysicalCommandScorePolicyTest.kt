package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PhysicalCommandScorePolicyTest {
    private val permissive = PhysicalCommandThresholds(
        minConfidence = 0.50f,
        minTopTwoMargin = 0.10f,
        minOppositeActionMargin = 0.20f,
    )

    @Test
    fun confidentPhysicalClassAuthorizes() {
        val decision = PhysicalCommandScorePolicy.decide(
            logits = floatArrayOf(8f, 0f, -1f, -1f, -2f),
            thresholds = permissive,
        )

        assertTrue(decision is PhysicalCommandDecision.Authorized)
        assertEquals(
            PhysicalCommandClass.TV_ON,
            (decision as PhysicalCommandDecision.Authorized).command,
        )
    }

    @Test
    fun otherAlwaysAbstains() {
        val decision = PhysicalCommandScorePolicy.decide(
            logits = floatArrayOf(-2f, -2f, -2f, -2f, 8f),
            thresholds = permissive,
        )

        assertTrue(decision is PhysicalCommandDecision.Abstain)
    }

    @Test
    fun closeOnOffEvidenceAbstainsOnOppositeMargin() {
        val decision = PhysicalCommandScorePolicy.decide(
            logits = floatArrayOf(2.0f, 1.9f, -4f, -4f, -4f),
            thresholds = PhysicalCommandThresholds(
                minConfidence = 0.40f,
                minTopTwoMargin = 0.01f,
                minOppositeActionMargin = 0.20f,
            ),
        )

        assertTrue(decision is PhysicalCommandDecision.Abstain)
        assertTrue((decision as PhysicalCommandDecision.Abstain).reason.contains("opposite-action"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun wrongLogitCountFailsClosedAtBoundary() {
        PhysicalCommandScorePolicy.decide(
            logits = floatArrayOf(1f, 2f),
            thresholds = permissive,
        )
    }
}
