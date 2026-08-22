package com.soul.aihub.voice

import kotlin.math.exp

/** Pure JVM-testable decision policy for five-class classifier logits. */
object PhysicalCommandScorePolicy {
    val CLASS_ORDER: List<PhysicalCommandClass> = listOf(
        PhysicalCommandClass.TV_ON,
        PhysicalCommandClass.TV_OFF,
        PhysicalCommandClass.AC_ON,
        PhysicalCommandClass.AC_OFF,
        PhysicalCommandClass.OTHER,
    )

    fun decide(
        logits: FloatArray,
        thresholds: PhysicalCommandThresholds,
    ): PhysicalCommandDecision {
        val probabilities = softmax(logits)
        val bestIndex = probabilities.indices.maxBy { probabilities[it] }
        val bestClass = CLASS_ORDER[bestIndex]
        val bestProbability = probabilities[bestIndex]

        if (bestClass == PhysicalCommandClass.OTHER) {
            return PhysicalCommandDecision.Abstain("acoustic classifier predicted OTHER")
        }

        val sorted = probabilities.sortedDescending()
        val topTwoMargin = sorted[0] - sorted[1]
        val oppositeIndex = oppositeActionIndex(bestIndex)
        val oppositeMargin = bestProbability - probabilities[oppositeIndex]

        if (bestProbability < thresholds.minConfidence) {
            return PhysicalCommandDecision.Abstain(
                "confidence below threshold: $bestProbability < ${thresholds.minConfidence}",
            )
        }
        if (topTwoMargin < thresholds.minTopTwoMargin) {
            return PhysicalCommandDecision.Abstain(
                "top-two margin below threshold: $topTwoMargin < ${thresholds.minTopTwoMargin}",
            )
        }
        if (oppositeMargin < thresholds.minOppositeActionMargin) {
            return PhysicalCommandDecision.Abstain(
                "opposite-action margin below threshold: $oppositeMargin < ${thresholds.minOppositeActionMargin}",
            )
        }

        return PhysicalCommandDecision.Authorized(
            command = bestClass,
            confidence = bestProbability,
            oppositeActionMargin = oppositeMargin,
        )
    }

    private fun softmax(logits: FloatArray): FloatArray {
        require(logits.size == CLASS_ORDER.size) {
            "expected ${CLASS_ORDER.size} logits, got ${logits.size}"
        }
        val max = logits.max()
        val exps = FloatArray(logits.size)
        var sum = 0.0
        logits.indices.forEach { i ->
            val value = exp((logits[i] - max).toDouble())
            exps[i] = value.toFloat()
            sum += value
        }
        require(sum.isFinite() && sum > 0.0) { "invalid classifier logits" }
        return FloatArray(logits.size) { i -> (exps[i] / sum).toFloat() }
    }

    private fun oppositeActionIndex(index: Int): Int = when (index) {
        0 -> 1
        1 -> 0
        2 -> 3
        3 -> 2
        else -> error("OTHER has no opposite physical action")
    }
}
