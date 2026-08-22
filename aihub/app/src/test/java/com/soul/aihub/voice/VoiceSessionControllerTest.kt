package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceSessionControllerTest {
    private class FakeAsr : StreamingAsrEngine {
        var finalText: String = ""
        var failBegin = false
        var failAccept = false
        var failFinish = false
        var beginCount = 0
        var resetCount = 0
        var closeCount = 0
        val acceptedSequences = mutableListOf<Long>()

        override fun begin(preRollPcm16: ShortArray) {
            beginCount += 1
            if (failBegin) error("synthetic ASR begin failure")
        }

        override fun accept(frame: PcmFrame): AsrUpdate? {
            if (failAccept) error("synthetic ASR accept failure")
            acceptedSequences += frame.sequence
            return null
        }

        override fun finish(): AsrUpdate {
            if (failFinish) error("synthetic ASR finish failure")
            return AsrUpdate(
                text = finalText,
                isFinal = true,
                producedAtElapsedRealtimeNs = 123L,
            )
        }

        override fun reset() {
            resetCount += 1
            acceptedSequences.clear()
        }

        override fun close() {
            closeCount += 1
        }
    }

    private class FakePhysicalAuthorizer(
        var decision: PhysicalCommandDecision,
    ) : PhysicalCommandAuthorizer {
        var beginCount = 0
        var finishCount = 0
        val acceptedSequences = mutableListOf<Long>()

        override fun reset() {
            acceptedSequences.clear()
        }

        override fun begin(preRollPcm16: ShortArray) {
            beginCount += 1
        }

        override fun accept(frame: PcmFrame) {
            acceptedSequences += frame.sequence
        }

        override fun finish(): PhysicalCommandDecision {
            finishCount += 1
            return decision
        }
    }

    private fun frame(sequence: Long, startSampleIndex: Long): PcmFrame = PcmFrame(
        samples = ShortArray(320) { 1 },
        capturedAtElapsedRealtimeNs = sequence * 20_000_000L,
        sequence = sequence,
        startSampleIndex = startSampleIndex,
    )

    private fun preRoll(
        endSampleIndexExclusive: Long = 0L,
        samples: ShortArray = ShortArray(0),
    ): PcmWindow = PcmWindow(
        samples = samples,
        startSampleIndex = endSampleIndexExclusive - samples.size.toLong(),
        endSampleIndexExclusive = endSampleIndexExclusive,
    )

    private fun requireGeneration(value: Long?): Long {
        assertNotNull(value)
        return value!!
    }

    private fun requireResult(value: VoiceSessionResult?): VoiceSessionResult {
        assertNotNull(value)
        return value!!
    }

    @Test
    fun acousticAuthorizationExecutesEvenWhenAsrTextSuggestsOppositeAction() {
        val asr = FakeAsr().apply { finalText = "옥자 TV 꺼줘" }
        val authorizer = FakePhysicalAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.TV_ON),
        )
        val executed = mutableListOf<PhysicalCommandClass>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.DeviceCommand(it) },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
            physicalCommandAuthorizer = authorizer,
        )

        val generation = requireGeneration(
            controller.startUtterance(preRoll(3_200L, shortArrayOf(7, 8))),
        )
        controller.acceptFrame(generation, frame(10, 3_200L))
        controller.acceptFrame(generation, frame(11, 3_520L))

        val result = requireResult(controller.finishUtterance(generation))

        assertEquals("옥자 TV 꺼줘", result.transcript)
        assertTrue(result.deviceCommandExecuted)
        assertFalse(result.blockedByAudioIntegrity)
        assertFalse(result.blockedByPhysicalAuthorization)
        assertEquals(listOf(PhysicalCommandClass.TV_ON), executed)
        assertEquals(1, authorizer.finishCount)
        assertEquals(VoiceSessionController.State.IDLE, controller.snapshot().state)

        assertNull(controller.finishUtterance(generation))
        assertEquals(1, executed.size)
    }

    @Test
    fun physicalAuthorizationSurvivesAsrBeginFailure() {
        val asr = FakeAsr().apply { failBegin = true }
        val authorizer = FakePhysicalAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.AC_ON),
        )
        val executed = mutableListOf<PhysicalCommandClass>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.Ignore },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
            physicalCommandAuthorizer = authorizer,
        )

        val generation = requireGeneration(controller.startUtterance(preRoll()))
        controller.acceptFrame(generation, frame(0, 0))
        val result = requireResult(controller.finishUtterance(generation))

        assertTrue(result.deviceCommandExecuted)
        assertEquals(listOf(PhysicalCommandClass.AC_ON), executed)
        assertEquals("", result.transcript)
    }

    @Test
    fun physicalAuthorizationSurvivesAsrAcceptFailure() {
        val asr = FakeAsr().apply { failAccept = true }
        val authorizer = FakePhysicalAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.TV_OFF),
        )
        val executed = mutableListOf<PhysicalCommandClass>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.Ignore },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
            physicalCommandAuthorizer = authorizer,
        )

        val generation = requireGeneration(controller.startUtterance(preRoll()))
        controller.acceptFrame(generation, frame(0, 0))
        val result = requireResult(controller.finishUtterance(generation))

        assertTrue(result.deviceCommandExecuted)
        assertEquals(listOf(PhysicalCommandClass.TV_OFF), executed)
        assertEquals(listOf(0L), authorizer.acceptedSequences)
        assertEquals("", result.transcript)
    }

    @Test
    fun physicalAuthorizationSurvivesAsrFinishFailure() {
        val asr = FakeAsr().apply { failFinish = true }
        val authorizer = FakePhysicalAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.AC_OFF),
        )
        val executed = mutableListOf<PhysicalCommandClass>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.Ignore },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
            physicalCommandAuthorizer = authorizer,
        )

        val generation = requireGeneration(controller.startUtterance(preRoll()))
        controller.acceptFrame(generation, frame(0, 0))
        val result = requireResult(controller.finishUtterance(generation))

        assertTrue(result.deviceCommandExecuted)
        assertEquals(listOf(PhysicalCommandClass.AC_OFF), executed)
        assertEquals("", result.transcript)
    }

    @Test
    fun preRollAloneCannotExecuteEvenWithAcousticAuthorization() {
        val authorizer = FakePhysicalAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.TV_ON),
        )
        val executed = mutableListOf<PhysicalCommandClass>()
        val controller = VoiceSessionController(
            asr = FakeAsr().apply { finalText = "옥자 TV 켜줘" },
            router = VoiceTranscriptRouter { VoiceRouteDecision.DeviceCommand(it) },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
            physicalCommandAuthorizer = authorizer,
        )

        val generation = requireGeneration(controller.startUtterance(preRoll(3_200L)))
        val result = requireResult(controller.finishUtterance(generation))

        assertFalse(result.deviceCommandExecuted)
        assertTrue(result.blockedByAudioIntegrity)
        assertTrue(executed.isEmpty())
    }

    @Test
    fun asrDeviceIntentCannotExecuteWithoutAcousticAuthorization() {
        val asr = FakeAsr().apply { finalText = "옥자 TV 켜줘" }
        val executed = mutableListOf<PhysicalCommandClass>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.DeviceCommand(it) },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
        )

        val generation = requireGeneration(controller.startUtterance(preRoll()))
        controller.acceptFrame(generation, frame(0, 0))
        val result = requireResult(controller.finishUtterance(generation))

        assertFalse(result.deviceCommandExecuted)
        assertTrue(result.blockedByPhysicalAuthorization)
        assertTrue(executed.isEmpty())
        assertTrue(result.physicalDecision is PhysicalCommandDecision.Abstain)
    }

    @Test
    fun discontinuousPcmFailsClosedEvenWithAcousticAuthorization() {
        val asr = FakeAsr().apply { finalText = "옥자 에어컨 꺼줘" }
        val authorizer = FakePhysicalAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.AC_OFF),
        )
        val executed = mutableListOf<PhysicalCommandClass>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.DeviceCommand(it) },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
            physicalCommandAuthorizer = authorizer,
        )

        val generation = requireGeneration(controller.startUtterance(preRoll()))
        controller.acceptFrame(generation, frame(0, 0))
        controller.acceptFrame(generation, frame(2, 640))

        val result = requireResult(controller.finishUtterance(generation))

        assertFalse(result.deviceCommandExecuted)
        assertTrue(result.blockedByAudioIntegrity)
        assertFalse(result.blockedByPhysicalAuthorization)
        assertTrue(executed.isEmpty())
        assertEquals(VoiceSessionController.State.IDLE, controller.snapshot().state)
    }

    @Test
    fun prerollToLiveGapFailsClosedEvenWithAcousticAuthorization() {
        val asr = FakeAsr().apply { finalText = "옥자 TV 켜줘" }
        val authorizer = FakePhysicalAuthorizer(
            PhysicalCommandDecision.Authorized(PhysicalCommandClass.TV_ON),
        )
        val executed = mutableListOf<PhysicalCommandClass>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.DeviceCommand(it) },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
            physicalCommandAuthorizer = authorizer,
        )

        val generation = requireGeneration(controller.startUtterance(preRoll(3_200L)))
        controller.acceptFrame(generation, frame(10, 3_520L))

        val result = requireResult(controller.finishUtterance(generation))

        assertFalse(result.deviceCommandExecuted)
        assertTrue(result.blockedByAudioIntegrity)
        assertTrue(executed.isEmpty())
    }

    @Test
    fun ttsCannotRecursivelyStartWakeAndFollowUpRequiresCurrentGeneration() {
        val asr = FakeAsr().apply { finalText = "옥자야 뭐하니" }
        val spoken = mutableListOf<Pair<String, Long>>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter {
                VoiceRouteDecision.Speak("응, 듣고 있어", expectFollowUp = true)
            },
            deviceExecutor = VoiceDeviceCommandExecutor { },
            speechOutput = VoiceSpeechOutput { text, generation -> spoken += text to generation },
        )

        val generation = requireGeneration(controller.startUtterance(preRoll()))
        controller.acceptFrame(generation, frame(0, 0))
        controller.finishUtterance(generation)

        assertEquals(VoiceSessionController.State.SPEAKING, controller.snapshot().state)
        assertEquals(listOf("응, 듣고 있어" to generation), spoken)
        assertNull(controller.startUtterance(preRoll(1L, shortArrayOf(1))))

        controller.onSpeechFinished(generation - 1L)
        assertEquals(VoiceSessionController.State.SPEAKING, controller.snapshot().state)

        controller.onSpeechFinished(generation)
        assertEquals(VoiceSessionController.State.FOLLOW_UP, controller.snapshot().state)

        val nextGeneration = requireGeneration(
            controller.startUtterance(preRoll(1L, shortArrayOf(1))),
        )
        assertTrue(nextGeneration > generation)
        assertEquals(VoiceSessionController.State.CAPTURING, controller.snapshot().state)
    }

    @Test
    fun staleFramesCannotContaminateANewerGeneration() {
        val asr = FakeAsr().apply { finalText = "ok" }
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.Ignore },
            deviceExecutor = VoiceDeviceCommandExecutor { },
            speechOutput = VoiceSpeechOutput { _, _ -> },
        )

        val oldGeneration = requireGeneration(controller.startUtterance(preRoll()))
        controller.onMicUnavailable()
        assertEquals(VoiceSessionController.State.MIC_OFF, controller.snapshot().state)

        controller.onMicAvailable()
        val currentGeneration = requireGeneration(controller.startUtterance(preRoll(3_200L)))

        assertNull(controller.acceptFrame(oldGeneration, frame(0, 0)))
        controller.acceptFrame(currentGeneration, frame(10, 3_200L))

        assertEquals(listOf(10L), asr.acceptedSequences)
    }

    @Test
    fun recoverableFailureBudgetIsBoundedAndRequiresExplicitRecovery() {
        val asr = FakeAsr().apply { finalText = "" }
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.Ignore },
            deviceExecutor = VoiceDeviceCommandExecutor { },
            speechOutput = VoiceSpeechOutput { _, _ -> },
            maxRecoverableFailures = 1,
        )

        val first = requireGeneration(controller.startUtterance(preRoll()))
        controller.acceptFrame(first, frame(0, 0))
        controller.finishUtterance(first)
        assertEquals(VoiceSessionController.State.IDLE, controller.snapshot().state)
        assertEquals(1, controller.snapshot().recoverableFailures)
        assertTrue(controller.snapshot().canRetry)

        val second = requireGeneration(controller.startUtterance(preRoll(3_200L)))
        controller.acceptFrame(second, frame(10, 3_200L))
        controller.finishUtterance(second)
        assertEquals(VoiceSessionController.State.DEGRADED, controller.snapshot().state)
        assertFalse(controller.snapshot().canRetry)
        assertNull(controller.startUtterance(preRoll()))

        controller.recoverFromDegraded()
        assertEquals(VoiceSessionController.State.IDLE, controller.snapshot().state)
        assertEquals(0, controller.snapshot().recoverableFailures)
    }
}
