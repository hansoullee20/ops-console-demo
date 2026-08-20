package com.soul.aihub.voice

/** ASR-agnostic routing result for one completed utterance. */
sealed interface VoiceRouteDecision {
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
    fun execute(command: String)
}

fun interface VoiceSpeechOutput {
    fun speak(text: String, generation: Long)
}

data class VoiceSessionResult(
    val generation: Long,
    val transcript: String,
    val route: VoiceRouteDecision?,
    val deviceCommandExecuted: Boolean,
    val blockedByAudioIntegrity: Boolean,
)

/**
 * Single authority for one voice interaction lifecycle.
 *
 * This class is deliberately independent from Android Activity lifecycle and microphone APIs.
 * AudioEngine remains the only microphone owner; callers feed the same canonical PCM frames here.
 * A single [StreamingAsrEngine] instance is reused across utterances, preventing parallel decoder
 * ownership while avoiding repeated model initialization.
 */
class VoiceSessionController(
    private val asr: StreamingAsrEngine,
    private val router: VoiceTranscriptRouter,
    private val deviceExecutor: VoiceDeviceCommandExecutor,
    private val speechOutput: VoiceSpeechOutput,
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

    /**
     * Starts one utterance using already-captured pre-roll from AudioEngine.
     * Returns the generation token that must accompany later callbacks/frames.
     *
     * While TTS is speaking, wake/capture requests are rejected so synthesized speech cannot
     * recursively start another command.
     */
    @Synchronized
    fun startUtterance(preRollPcm16: ShortArray): Long? {
        check(!closed) { "controller is closed" }
        if (state !in setOf(State.IDLE, State.FOLLOW_UP)) return null

        generation += 1L
        followUpAfterSpeech = false
        utteranceActive = false
        asr.reset()
        integrity.beginUtterance()

        return try {
            asr.begin(preRollPcm16)
            utteranceActive = true
            state = State.CAPTURING
            generation
        } catch (t: Throwable) {
            integrity.endUtterance()
            noteRecoverableFailureLocked()
            null
        }
    }

    /** Frames from an older generation are ignored instead of contaminating the active utterance. */
    @Synchronized
    fun acceptFrame(callbackGeneration: Long, frame: PcmFrame): AsrUpdate? {
        check(!closed) { "controller is closed" }
        if (callbackGeneration != generation || state != State.CAPTURING || !utteranceActive) {
            return null
        }

        return try {
            integrity.observe(frame)
            asr.accept(frame)
        } catch (t: Throwable) {
            abortUtteranceLocked()
            noteRecoverableFailureLocked()
            null
        }
    }

    /**
     * Finishes and routes the current utterance exactly once.
     *
     * Device commands are executed only when the entire observed utterance remained PCM-contiguous.
     * The transcript is routed as a whole, so a command suffix already present after the wake phrase
     * is never discarded in favor of a second recognizer pass.
     */
    @Synchronized
    fun finishUtterance(callbackGeneration: Long): VoiceSessionResult? {
        check(!closed) { "controller is closed" }
        if (callbackGeneration != generation || state != State.CAPTURING || !utteranceActive) {
            return null
        }

        state = State.ROUTING
        val update = try {
            asr.finish()
        } catch (t: Throwable) {
            abortUtteranceLocked()
            noteRecoverableFailureLocked()
            return null
        }

        val transcript = update?.text?.trim().orEmpty()
        if (transcript.isBlank()) {
            abortUtteranceLocked()
            noteRecoverableFailureLocked()
            return VoiceSessionResult(
                generation = generation,
                transcript = "",
                route = null,
                deviceCommandExecuted = false,
                blockedByAudioIntegrity = false,
            )
        }

        val route = try {
            router.route(transcript)
        } catch (t: Throwable) {
            abortUtteranceLocked()
            state = State.DEGRADED
            return null
        }

        val audioTrusted = integrity.canAuthorizeDeviceCommand()
        endUtteranceLocked()
        recoverableFailures = 0

        var executed = false
        var blockedByAudioIntegrity = false

        when (route) {
            is VoiceRouteDecision.DeviceCommand -> {
                if (audioTrusted) {
                    try {
                        deviceExecutor.execute(route.command)
                        executed = true
                    } catch (t: Throwable) {
                        state = State.DEGRADED
                        return VoiceSessionResult(
                            generation = generation,
                            transcript = transcript,
                            route = route,
                            deviceCommandExecuted = false,
                            blockedByAudioIntegrity = false,
                        )
                    }
                } else {
                    blockedByAudioIntegrity = true
                }

                val confirmation = route.spokenConfirmation
                if (!confirmation.isNullOrBlank()) {
                    followUpAfterSpeech = false
                    state = State.SPEAKING
                    speechOutput.speak(confirmation, generation)
                } else {
                    state = State.IDLE
                }
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
            deviceCommandExecuted = executed,
            blockedByAudioIntegrity = blockedByAudioIntegrity,
        )
    }

    /** Stale TTS callbacks cannot change the state of a newer session. */
    @Synchronized
    fun onSpeechFinished(callbackGeneration: Long) {
        check(!closed) { "controller is closed" }
        if (callbackGeneration != generation || state != State.SPEAKING) return
        state = if (followUpAfterSpeech) State.FOLLOW_UP else State.IDLE
        followUpAfterSpeech = false
    }

    /** Any active work is invalidated immediately when microphone access becomes unavailable. */
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

    /** Explicit recovery is required after the bounded failure budget is exhausted. */
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
        try {
            asr.reset()
        } catch (_: Throwable) {
            // The caller will move to DEGRADED/MIC_OFF as appropriate; never let cleanup recurse.
        }
    }

    private fun noteRecoverableFailureLocked() {
        recoverableFailures += 1
        state = if (recoverableFailures > maxRecoverableFailures) State.DEGRADED else State.IDLE
    }
}
