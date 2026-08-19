package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceAudioContractTest {
    @Test
    fun canonicalFrameAndBufferDefaultsMatchArchitecture() {
        assertEquals(16_000, AudioEngine.SAMPLE_RATE_HZ)
        assertEquals(20, AudioEngine.FRAME_MS)
        assertEquals(320, AudioEngine.FRAME_SAMPLES)
        assertEquals(3_000, AudioEngine.DEFAULT_RING_CAPACITY_MS)
        assertEquals(1_500, AudioEngine.DEFAULT_PRE_ROLL_MS)
    }

    @Test
    fun wakeAndAsrContractsArePcmConsumersOnly() {
        val wakeMethods = WakeDetector::class.java.methods.map { it.name }.toSet()
        val asrMethods = StreamingAsrEngine::class.java.methods.map { it.name }.toSet()

        assertTrue("WakeDetector must expose PCM accept", "accept" in wakeMethods)
        assertTrue("StreamingAsrEngine must expose PCM accept", "accept" in asrMethods)
        assertTrue("StreamingAsrEngine must expose pre-roll begin", "begin" in asrMethods)
        assertTrue("StreamingAsrEngine must not own capture lifecycle", "startRecording" !in asrMethods)
        assertTrue("WakeDetector must not own capture lifecycle", "startRecording" !in wakeMethods)
    }
}
