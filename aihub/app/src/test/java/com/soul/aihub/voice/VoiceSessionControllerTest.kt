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
        var beginCount = 0
        var resetCount = 0
        var closeCount = 0
        val acceptedSequences = mutableListOf<Long>()

        override fun begin(preRollPcm16: ShortArray) {
            beginCount += 1
        }

        override fun accept(frame: PcmFrame): AsrUpdate? {
            acceptedSequences += frame.sequence
            return null
        }

        override fun finish(): AsrUpdate {
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

    private fun frame(sequence: Long, startSampleIndex: Long): PcmFrame {
        return PcmFrame(
            samples = ShortArray(320) { 1 },
            capturedAtElapsedRealtimeNs = sequence * 20_000_000L,
            sequence = sequence,
            startSampleIndex = startSampleIndex,
        )
    }

    @Test
    fun routesWholeWakeCommandAndExecutesExactlyOnceWhenPcmIsContinuous() {
        val asr = FakeAsr().apply { finalText = "옥자 TV 켜줘" }
        val executed = mutableListOf<String>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.DeviceCommand(it) },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
        )

        val generation = assertNotNull(controller.startUtterance(shortArrayOf(7, 8))) as Long
        controller.acceptFrame(generation, frame(10, 3200))
        controller.acceptFrame(generation, frame(11, 3520))

        val result = assertNotNull(controller.finishUtterance(generation)) as VoiceSessionResult

        assertEquals("옥자 TV 켜줘", result.transcript)
        assertTrue(result.deviceCommandExecuted)
        assertFalse(result.blockedByAudioIntegrity)
        assertEquals(listOf("옥자 TV 켜줘"), executed)
        assertEquals(VoiceSessionController.State.IDLE, controller.snapshot().state)

        // A duplicate/stale finish callback for the same generation is ignored.
        assertNull(controller.finishUtterance(generation))
        assertEquals(1, executed.size)
    }

    @Test
    fun discontinuousPcmFailsClosedBeforePhysicalExecution() {
        val asr = FakeAsr().apply { finalText = "옥자 에어컨 꺼줘" }
        val executed = mutableListOf<String>()
        val controller = VoiceSessionController(
            asr = asr,
            router = VoiceTranscriptRouter { VoiceRouteDecision.DeviceCommand(it) },
            deviceExecutor = VoiceDeviceCommandExecutor { executed += it },
            speechOutput = VoiceSpeechOutput { _, _ -> },
        )

        val generation = assertNotNull(controller.startUtterance(shortArrayOf())) as Long
        controller.acceptFrame(generation, frame(0, 0))
        controller.acceptFrame(generation, frame(2, 640)) // frame 1 / samples 320..639 missing

        val result = assertNotNull(controller.finishUtterance(generation)) as VoiceSessionResult

        assertFalse(result.deviceCommandExecuted)
        assertTrue(result.blockedByAudioIntegrity)
        assertTrue(executed.isEmpty())
        assertEquals(VoiceSessionController.State.IDLE, controller.snapshot().state)
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

        val generation = assertNotNull(controller.startUtterance(shortArrayOf())) as Long
        controller.acceptFrame(generation, frame(0, 0))
        controller.finishUtterance(generation)

        assertEquals(VoiceSessionController.State.SPEAKING, controller.snapshot().state)
        assertEquals(listOf("응, 듣고 있어" to generation), spoken)
        assertNull(controller.startUtterance(shortArrayOf(1)))

        controller.onSpeechFinished(generation - 1L)
        assertEquals(VoiceSessionController.State.SPEAKING, controller.snapshot().state)

        controller.onSpeechFinished(generation)
        assertEquals(VoiceSessionController.State.FOLLOW_UP, controller.snapshot().state)

        val nextGeneration = assertNotNull(controller.startUtterance(shortArrayOf(1))) as Long
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

        val oldGeneration = assertNotNull(controller.startUtterance(shortArrayOf())) as Long
        controller.onMicUnavailable()
        assertEquals(VoiceSessionController.State.MIC_OFF, controller.snapshot().state)

        controller.onMicAvailable()
        val currentGeneration = assertNotNull(controller.startUtterance(shortArrayOf())) as Long

        assertNull(controller.acceptFrame(oldGeneration, frame(0, 0)))
        controller.acceptFrame(currentGeneration, frame(10, 3200))

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

        val first = assertNotNull(controller.startUtterance(shortArrayOf())) as Long
        controller.acceptFrame(first, frame(0, 0))
        controller.finishUtterance(first)
        assertEquals(VoiceSessionController.State.IDLE, controller.snapshot().state)
        assertEquals(1, controller.snapshot().recoverableFailures)
        assertTrue(controller.snapshot().canRetry)

        val second = assertNotNull(controller.startUtterance(shortArrayOf())) as Long
        controller.acceptFrame(second, frame(10, 3200))
        controller.finishUtterance(second)
        assertEquals(VoiceSessionController.State.DEGRADED, controller.snapshot().state)
        assertFalse(controller.snapshot().canRetry)
        assertNull(controller.startUtterance(shortArrayOf()))

        controller.recoverFromDegraded()
        assertEquals(VoiceSessionController.State.IDLE, controller.snapshot().state)
        assertEquals(0, controller.snapshot().recoverableFailures)
    }
}
