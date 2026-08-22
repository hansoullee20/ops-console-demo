package com.soul.aihub.voice

/** ASR-agnostic routing result for one completed utterance. */
sealed interface VoiceRouteDecision {
    /**
     * Diagnostic/semantic device intent from ASR text only.
     * This can never authorize physical execution by itself.
     */
    data class DeviceCommand(
        val command: String,
        val spokenConfirmation: String? = null,
    ) : VoiceRouteDecision

    data class Speak(
        val text: String,
        val expectFollowUp: Boolean = false,
    ) : VoiceRouteDecision

    data object Ignore : VoiceRouteDecision
}

fun interface VoiceTranscriptRouter {
    fun route(transcript: String): VoiceRouteDecision
}

fun interface VoiceDeviceCommandExecutor {
    fun execute(command: PhysicalCommandClass)
}

fun interface VoiceSpeechOutput {
    fun speak(text: String, generation: Long)
}

data class VoiceSessionResult(
    val generation: Long,
    val transcript: String,
    val route: VoiceRouteDecision?,
    val physicalDecision: PhysicalCommandDecision,
    val deviceCommandExecuted: Boolean,
    val blockedByAudioIntegrity: Boolean,
    val blockedByPhysicalAuthorization: Boolean,
)

/**
 * Single authority for one voice interaction lifecycle.
 *
 * AudioEngine remains the only microphone owner. Physical execution requires an independent
 * caller-owned-PCM authorizer; ASR text and the transcript router are never actuator authority.
 *
 * A session can start only from a [PcmWindow] carrying the exact pre-roll sample range. This lets
 * the integrity gate prove that the first live frame begins exactly where pre-roll ended.
 */
class VoiceSessionController(
    private val asr: StreamingAsrEngine,
    private val router: VoiceTranscriptRouter,
    private val deviceExecutor: VoiceDeviceCommandExecutor,
    private val speechOutput: VoiceSpeechOutput,
    private val physicalCommandAuthorizer: PhysicalCommandAuthorizer = RejectingPhysicalCommandAuthorizer,
    private val maxRecoverableFailures: Int = 1,
) : AutoCloseable {
    enum class State {
        IDLE,
        CAPTURING,
        ROUTING,
        SPEAKING,
        FOLLOW_UP,
        MIC_OFF,
        DEGRADED,
    }

    data class Snapshot(
        val state: State,
        val generation: Long,
        val recoverableFailures: Int,
        val canRetry: Boolean,
    )

    private val integrity = UtteranceAudioIntegrityGate()
    private var state = State.IDLE
    private var generation = 0L
    private var recoverableFailures = 0
    private var followUpAfterSpeech = false
    private var closed = false
    private var utteranceActive = false
    private var physicalAuthorizerHealthy = false

    init {
        require(maxRecoverableFailures >= 0) { "maxRecoverableFailures must be >= 0" }
    }

    @Synchronized
    fun snapshot(): Snapshot = Snapshot(
        state = state,
        generation = generation,
        recoverableFailures = recoverableFailures,
        canRetry = recoverableFailures <= maxRecoverableFailures && state != State.DEGRADED,
    )

    @Synchronized
    fun startUtterance(preRoll: PcmWindow): Long? {
        check(!closed) { "controller is closed" }
        if (state !in setOf(State.IDLE, State.FOLLOW_UP)) return null

        generation += 1L
        followUpAfterSpeech = false
        utteranceActive = false
        physicalAuthorizerHealthy = false
        asr.reset()
        try {
            physicalCommandAuthorizer.reset()
            physicalCommandAuthorizer.begin(preRoll.samples)
            physicalAuthorizerHealthy = true
        } catch (_: Throwable) {
            physicalAuthorizerHealthy = false
        }
        integrity.beginUtterance(preRoll.endSampleIndexExclusive)

        return try {
            asr.begin(preRoll.samples)
            utteranceActive = true
            state = State.CAPTURING
            generation
        } catch (_: Throwable) {
            integrity.endUtterance()
            safeResetPhysicalAuthorizerLocked()
            noteRecoverableFailureLocked()
            null
        }
    }

    @Synchronized
    fun acceptFrame(callbackGeneration: Long, frame: PcmFrame): AsrUpdate? {
        check(!closed) { "controller is closed" }
        if (callbackGeneration != generation || state != State.CAPTURING || !utteranceActive) {
            return null
        }

        return try {
            integrity.observe(frame)
            if (physicalAuthorizerHealthy) {
                try {
                    physicalCommandAuthorizer.accept(frame)
                } catch (_: Throwable) {
                    physicalAuthorizerHealthy = false
                    safeResetPhysicalAuthorizerLocked()
                }
            }
            asr.accept(frame)
        } catch (_: Throwable) {
            abortUtteranceLocked()
            noteRecoverableFailureLocked()
            null
        }
    }

    @Synchronized
    fun finishUtterance(callbackGeneration: Long): VoiceSessionResult? {
        check(!closed) { "controller is closed" }
        if (callbackGeneration != generation || state != State.CAPTURING || !utteranceActive) {
            return null
        }

        state = State.ROUTING
        val physicalDecision = if (physicalAuthorizerHealthy) {
            try {
                physicalCommandAuthorizer.finish()
            } catch (_: Throwable) {
                PhysicalCommandDecision.Abstain("physical-command authorizer failed")
            }
        } else {
            PhysicalCommandDecision.Abstain("physical-command authorizer unavailable")
        }
        physicalAuthorizerHealthy = false

        val update = try {
            asr.finish()
        } catch (_: Throwable) {
            abortUtteranceLocked()
            noteRecoverableFailureLocked()
            return null
        }

        val transcript = update?.text?.trim().orEmpty()
        val audioTrusted = integrity.canAuthorizeDeviceCommand()
        endUtteranceLocked()

        if (physicalDecision is PhysicalCommandDecision.Authorized) {
            recoverableFailures = 0
            if (!audioTrusted) {
                state = State.IDLE
                return VoiceSessionResult(
                    generation = generation,
                    transcript = transcript,
                    route = null,
                    physicalDecision = physicalDecision,
                    deviceCommandExecuted = false,
                    blockedByAudioIntegrity = true,
                    blockedByPhysicalAuthorization = false,
                )
            }

            return try {
                deviceExecutor.execute(physicalDecision.command)
                state = State.IDLE
                VoiceSessionResult(
                    generation = generation,
                    transcript = transcript,
                    route = null,
                    physicalDecision = physicalDecision,
                    deviceCommandExecuted = true,
                    blockedByAudioIntegrity = false,
                    blockedByPhysicalAuthorization = false,
                )
            } catch (_: Throwable) {
                state = State.DEGRADED
                VoiceSessionResult(
                    generation = generation,
                    transcript = transcript,
                    route = null,
                    physicalDecision = physicalDecision,
                    deviceCommandExecuted = false,
                    blockedByAudioIntegrity = false,
                    blockedByPhysicalAuthorization = false,
                )
            }
        }

        if (transcript.isBlank()) {
            noteRecoverableFailureLocked()
            return VoiceSessionResult(
                generation = generation,
                transcript = "",
                route = null,
                physicalDecision = physicalDecision,
                deviceCommandExecuted = false,
                blockedByAudioIntegrity = false,
                blockedByPhysicalAuthorization = false,
            )
        }

        val route = try {
            router.route(transcript)
        } catch (_: Throwable) {
            state = State.DEGRADED
            return null
        }

        recoverableFailures = 0
        var blockedByPhysicalAuthorization = false

        when (route) {
            is VoiceRouteDecision.DeviceCommand -> {
                // ASR/router evidence is diagnostic only. Require a fresh acoustic authorization.
                blockedByPhysicalAuthorization = true
                state = State.IDLE
            }

            is VoiceRouteDecision.Speak -> {
                followUpAfterSpeech = route.expectFollowUp
                state = State.SPEAKING
                speechOutput.speak(route.text, generation)
            }

            VoiceRouteDecision.Ignore -> {
                state = State.IDLE
            }
        }

        return VoiceSessionResult(
            generation = generation,
            transcript = transcript,
            route = route,
            physicalDecision = physicalDecision,
            deviceCommandExecuted = false,
            blockedByAudioIntegrity = false,
            blockedByPhysicalAuthorization = blockedByPhysicalAuthorization,
        )
    }

    @Synchronized
    fun onSpeechFinished(callbackGeneration: Long) {
        check(!closed) { "controller is closed" }
        if (callbackGeneration != generation || state != State.SPEAKING) return
        state = if (followUpAfterSpeech) State.FOLLOW_UP else State.IDLE
        followUpAfterSpeech = false
    }

    @Synchronized
    fun onMicUnavailable() {
        check(!closed) { "controller is closed" }
        generation += 1L
        abortUtteranceLocked()
        followUpAfterSpeech = false
        state = State.MIC_OFF
    }

    @Synchronized
    fun onMicAvailable() {
        check(!closed) { "controller is closed" }
        if (state == State.MIC_OFF) {
            recoverableFailures = 0
            state = State.IDLE
        }
    }

    @Synchronized
    fun recoverFromDegraded() {
        check(!closed) { "controller is closed" }
        if (state == State.DEGRADED) {
            generation += 1L
            recoverableFailures = 0
            followUpAfterSpeech = false
            abortUtteranceLocked()
            state = State.IDLE
        }
    }

    @Synchronized
    override fun close() {
        if (closed) return
        closed = true
        generation += 1L
        abortUtteranceLocked()
        followUpAfterSpeech = false
        asr.close()
        try {
            physicalCommandAuthorizer.close()
        } catch (_: Throwable) {
            // Closing cannot reopen authority or change lifecycle state.
        }
    }

    private fun endUtteranceLocked() {
        if (utteranceActive) {
            integrity.endUtterance()
            utteranceActive = false
        }
    }

    private fun abortUtteranceLocked() {
        if (utteranceActive) {
            integrity.endUtterance()
            utteranceActive = false
        }
        physicalAuthorizerHealthy = false
        safeResetPhysicalAuthorizerLocked()
        try {
            asr.reset()
        } catch (_: Throwable) {
            // The caller will move to DEGRADED/MIC_OFF as appropriate; never let cleanup recurse.
        }
    }

    private fun safeResetPhysicalAuthorizerLocked() {
        try {
            physicalCommandAuthorizer.reset()
        } catch (_: Throwable) {
            // Failure is fail-closed because physicalAuthorizerHealthy remains false.
        }
    }

    private fun noteRecoverableFailureLocked() {
        recoverableFailures += 1
        state = if (recoverableFailures > maxRecoverableFailures) State.DEGRADED else State.IDLE
    }
}
