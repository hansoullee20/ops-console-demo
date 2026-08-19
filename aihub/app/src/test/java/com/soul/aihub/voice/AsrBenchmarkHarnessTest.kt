package com.soul.aihub.voice

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AsrBenchmarkHarnessTest {
    private class RecordingEngine(
        private val finalText: String,
        private val partialAtNs: Long = 40_000_000L,
        private val finalAtNs: Long = 80_000_000L,
    ) : StreamingAsrEngine {
        var preRoll: ShortArray = ShortArray(0)
        val accepted = mutableListOf<PcmFrame>()
        private var emittedPartial = false

        override fun begin(preRollPcm16: ShortArray) {
            preRoll = preRollPcm16.copyOf()
        }

        override fun accept(frame: PcmFrame): AsrUpdate? {
            accepted += frame.copy(samples = frame.samples.copyOf())
            if (!emittedPartial) {
                emittedPartial = true
                return AsrUpdate("옥자야", false, partialAtNs)
            }
            return null
        }

        override fun finish(): AsrUpdate = AsrUpdate(finalText, true, finalAtNs)

        override fun reset() {
            accepted.clear()
            emittedPartial = false
        }
    }

    @Test
    fun replaysExactPcmWithCanonicalFrameMetadata() {
        val pcm = ShortArray(800) { it.toShort() }
        val engine = RecordingEngine("옥자 TV 켜줘")
        val case = RecordedPcmCase(
            id = "tv-on",
            pcm16 = pcm,
            expectedTranscript = "옥자 TV 켜줘",
            expectedCommandSuffix = "TV 켜줘",
            preRollSamples = 160,
        )

        val result = AsrBenchmarkHarness().run(case, "fake", engine)

        assertArrayEquals(pcm.copyOfRange(0, 160), engine.preRoll)
        assertEquals(2, engine.accepted.size)
        assertArrayEquals(pcm.copyOfRange(160, 480), engine.accepted[0].samples)
        assertArrayEquals(pcm.copyOfRange(480, 800), engine.accepted[1].samples)
        assertEquals(0L, engine.accepted[0].sequence)
        assertEquals(160L, engine.accepted[0].startSampleIndex)
        assertEquals(1L, engine.accepted[1].sequence)
        assertEquals(480L, engine.accepted[1].startSampleIndex)
        assertFalse(result.discontinuityDetected)
        assertTrue(result.transcriptMatchesExpected == true)
        assertTrue(result.commandSuffixPreserved == true)
        assertEquals(40L, result.firstPartialLatencyMs)
        assertEquals(80L, result.finalLatencyMs)
    }

    @Test
    fun identicalCaseProducesIdenticalPcmForDifferentEngines() {
        val pcm = ShortArray(960) { (it * 3).toShort() }
        val case = RecordedPcmCase(id = "same-pcm", pcm16 = pcm)
        val first = RecordingEngine("옥자야 뭐하니")
        val second = RecordingEngine("옥자야 뭐하니")
        val harness = AsrBenchmarkHarness()

        harness.run(case, "engine-a", first)
        harness.run(case, "engine-b", second)

        assertEquals(first.accepted.size, second.accepted.size)
        first.accepted.indices.forEach { index ->
            assertArrayEquals(first.accepted[index].samples, second.accepted[index].samples)
            assertEquals(first.accepted[index].sequence, second.accepted[index].sequence)
            assertEquals(first.accepted[index].startSampleIndex, second.accepted[index].startSampleIndex)
        }
    }

    @Test
    fun latencyIsRelativeToCaptureStartNotAbsoluteMonotonicTime() {
        val startNs = 5_000_000_000L
        val engine = RecordingEngine(
            finalText = "옥자야 뭐하니",
            partialAtNs = startNs + 25_000_000L,
            finalAtNs = startNs + 75_000_000L,
        )
        val case = RecordedPcmCase(id = "clock", pcm16 = ShortArray(320))

        val result = AsrBenchmarkHarness().run(
            case = case,
            engineName = "fake",
            engine = engine,
            captureStartElapsedRealtimeNs = startNs,
        )

        assertEquals(25L, result.firstPartialLatencyMs)
        assertEquals(75L, result.finalLatencyMs)
        assertEquals(startNs, engine.accepted.single().capturedAtElapsedRealtimeNs)
    }

    @Test
    fun reportsMissingExpectedCommandSuffix() {
        val engine = RecordingEngine("옥자")
        val case = RecordedPcmCase(
            id = "suffix-loss",
            pcm16 = ShortArray(320),
            expectedCommandSuffix = "에어컨 꺼줘",
        )

        val result = AsrBenchmarkHarness().run(case, "fake", engine)

        assertFalse(result.commandSuffixPreserved == true)
        assertEquals("옥자", result.finalTranscript)
    }
}
