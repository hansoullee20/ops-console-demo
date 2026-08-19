package com.soul.aihub.voice

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class PcmRingBufferTest {
    @Test
    fun returnsNewestRequestedWindowWithoutWrap() {
        val ring = PcmRingBuffer(sampleRateHz = 10, capacityMs = 3000)
        ring.append(shortArrayOf(1, 2, 3, 4, 5, 6, 7, 8, 9, 10))

        assertArrayEquals(shortArrayOf(6, 7, 8, 9, 10), ring.snapshotLatest(500))
    }

    @Test
    fun returnsNewestWindowAcrossWrap() {
        val ring = PcmRingBuffer(sampleRateHz = 10, capacityMs = 1000)
        ring.append(shortArrayOf(1, 2, 3, 4, 5, 6, 7, 8))
        ring.append(shortArrayOf(9, 10, 11, 12, 13, 14))

        assertEquals(10, ring.bufferedSamples())
        assertArrayEquals(
            shortArrayOf(5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
            ring.snapshotLatest(1000),
        )
        assertArrayEquals(shortArrayOf(10, 11, 12, 13, 14), ring.snapshotLatest(500))
    }

    @Test
    fun capacityAndPrerollAreIndependent() {
        val ring = PcmRingBuffer(sampleRateHz = 16_000, capacityMs = 3000)
        assertEquals(48_000, ring.capacitySamples())

        val oneSecond = ShortArray(16_000) { it.toShort() }
        ring.append(oneSecond)
        assertEquals(16_000, ring.snapshotLatest(1500).size)
    }
}
