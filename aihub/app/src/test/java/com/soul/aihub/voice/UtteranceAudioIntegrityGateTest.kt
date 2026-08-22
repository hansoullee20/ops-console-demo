package com.soul.aihub.voice

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UtteranceAudioIntegrityGateTest {
    private fun frame(sequence: Long, startSampleIndex: Long): PcmFrame {
        return PcmFrame(
            samples = ShortArray(320),
            capturedAtElapsedRealtimeNs = sequence * 20_000_000L,
            sequence = sequence,
            startSampleIndex = startSampleIndex,
        )
    }

    @Test
    fun contiguousUtteranceCanAuthorizeDeviceCommand() {
        val gate = UtteranceAudioIntegrityGate()
        gate.beginUtterance(expectedFirstLiveSampleIndex = 0L)

        gate.observe(frame(0, 0))
        gate.observe(frame(1, 320))

        assertTrue(gate.canAuthorizeDeviceCommand())
    }

    @Test
    fun gapLatchesUtteranceUntrustedUntilNewUtteranceBegins() {
        val gate = UtteranceAudioIntegrityGate()
        gate.beginUtterance(expectedFirstLiveSampleIndex = 0L)
        gate.observe(frame(0, 0))

        gate.observe(frame(2, 640))
        assertFalse(gate.canAuthorizeDeviceCommand())

        gate.observe(frame(3, 960))
        assertFalse(gate.canAuthorizeDeviceCommand())

        gate.beginUtterance(expectedFirstLiveSampleIndex = 3_200L)
        gate.observe(frame(10, 3_200L))
        assertTrue(gate.canAuthorizeDeviceCommand())
    }

    @Test
    fun gapBetweenPrerollAndFirstLiveFrameFailsClosed() {
        val gate = UtteranceAudioIntegrityGate()
        gate.beginUtterance(expectedFirstLiveSampleIndex = 3_200L)

        gate.observe(frame(10, 3_520L))

        assertFalse(gate.canAuthorizeDeviceCommand())
    }

    @Test
    fun endedUtteranceCannotAuthorize() {
        val gate = UtteranceAudioIntegrityGate()
        gate.beginUtterance(expectedFirstLiveSampleIndex = 0L)
        gate.observe(frame(0, 0))
        gate.endUtterance()

        assertFalse(gate.canAuthorizeDeviceCommand())
    }
}
