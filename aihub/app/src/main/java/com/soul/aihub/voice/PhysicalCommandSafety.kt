package com.soul.aihub.voice

enum class PhysicalDevice {
    TV,
    AIR_CONDITIONER,
}

enum class PhysicalAction {
    ON,
    OFF,
}

enum class PhysicalCommandClass(
    val device: PhysicalDevice?,
    val action: PhysicalAction?,
) {
    TV_ON(PhysicalDevice.TV, PhysicalAction.ON),
    TV_OFF(PhysicalDevice.TV, PhysicalAction.OFF),
    AC_ON(PhysicalDevice.AIR_CONDITIONER, PhysicalAction.ON),
    AC_OFF(PhysicalDevice.AIR_CONDITIONER, PhysicalAction.OFF),
    OTHER(null, null),
    ;

    val isPhysical: Boolean
        get() = this != OTHER
}

sealed interface PhysicalCommandDecision {
    data class Authorized(
        val command: PhysicalCommandClass,
        val confidence: Float? = null,
        val oppositeActionMargin: Float? = null,
    ) : PhysicalCommandDecision {
        init {
            require(command.isPhysical) { "OTHER cannot authorize a physical command" }
            confidence?.let { require(it in 0f..1f) { "confidence must be in [0, 1]" } }
            oppositeActionMargin?.let { require(it >= 0f) { "oppositeActionMargin must be non-negative" } }
        }
    }

    data class Abstain(val reason: String) : PhysicalCommandDecision {
        init {
            require(reason.isNotBlank()) { "abstain reason must not be blank" }
        }
    }
}

/**
 * Microphone-free physical-command authority.
 *
 * Implementations consume the exact caller-owned PCM stream used by the rest of Okja. They must
 * never acquire AudioRecord themselves. A production implementation will wrap the five-class
 * acoustic model {TV_ON, TV_OFF, AC_ON, AC_OFF, OTHER} plus calibrated abstention thresholds.
 */
interface PhysicalCommandAuthorizer : AutoCloseable {
    fun reset()
    fun begin(preRollPcm16: ShortArray)
    fun accept(frame: PcmFrame)
    fun finish(): PhysicalCommandDecision
    override fun close() {}
}

/** Default until a qualified classifier is installed: physical execution is impossible. */
object RejectingPhysicalCommandAuthorizer : PhysicalCommandAuthorizer {
    override fun reset() = Unit
    override fun begin(preRollPcm16: ShortArray) = Unit
    override fun accept(frame: PcmFrame) = Unit
    override fun finish(): PhysicalCommandDecision =
        PhysicalCommandDecision.Abstain("no physical-command classifier configured")
}

enum class PhysicalCommandOutcome {
    CORRECT,
    ABSTAIN,
    WRONG_DEVICE,
    WRONG_ACTION,
    FALSE_PHYSICAL_EXECUTION,
}

data class PhysicalCommandEvaluation(
    val expected: PhysicalCommandClass,
    val decision: PhysicalCommandDecision,
    val outcome: PhysicalCommandOutcome,
    val oppositeActionInversion: Boolean,
)

/** Safety-oriented scoring for the command benchmark. Generic WER/CER is deliberately irrelevant. */
object PhysicalCommandSafetyEvaluator {
    fun evaluate(
        expected: PhysicalCommandClass,
        decision: PhysicalCommandDecision,
    ): PhysicalCommandEvaluation {
        val outcome: PhysicalCommandOutcome
        var inversion = false

        when (decision) {
            is PhysicalCommandDecision.Abstain -> {
                outcome = PhysicalCommandOutcome.ABSTAIN
            }

            is PhysicalCommandDecision.Authorized -> {
                val predicted = decision.command
                outcome = when {
                    expected == PhysicalCommandClass.OTHER -> {
                        PhysicalCommandOutcome.FALSE_PHYSICAL_EXECUTION
                    }

                    predicted == expected -> {
                        PhysicalCommandOutcome.CORRECT
                    }

                    predicted.device != expected.device -> {
                        PhysicalCommandOutcome.WRONG_DEVICE
                    }

                    predicted.action != expected.action -> {
                        inversion = true
                        PhysicalCommandOutcome.WRONG_ACTION
                    }

                    else -> error("unreachable physical-command comparison")
                }
            }
        }

        return PhysicalCommandEvaluation(
            expected = expected,
            decision = decision,
            outcome = outcome,
            oppositeActionInversion = inversion,
        )
    }
}
