package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Test

class FixedPcmFrameAccumulatorTest {
    @Test
    fun adaptsTwentyMillisecondFramesWithoutDroppingSamples() {
        val accumulator = FixedPcmFrameAccumulator(frameSamples = 512)
        val emitted = mutableListOf<ShortArray>()

        accumulator.accept(ShortArray(320) { it.toShort() }) { emitted += it }
        assertEquals(0, emitted.size)
        assertEquals(320, accumulator.pendingSamples())

        accumulator.accept(ShortArray(320) { (320 + it).toShort() }) { emitted += it }
        assertEquals(1, emitted.size)
        assertEquals(128, accumulator.pendingSamples())
        assertEquals((0 until 512).map { it.toShort() }, emitted.single().toList())

        accumulator.accept(ShortArray(384) { (640 + it).toShort() }) { emitted += it }
        assertEquals(2, emitted.size)
        assertEquals(0, accumulator.pendingSamples())
        assertEquals((512 until 1024).map { it.toShort() }, emitted[1].toList())
    }

    @Test
    fun resetDropsOnlyPendingPartialFrame() {
        val accumulator = FixedPcmFrameAccumulator(frameSamples = 512)
        val emitted = mutableListOf<ShortArray>()

        accumulator.accept(ShortArray(320) { 1 }) { emitted += it }
        accumulator.reset()
        accumulator.accept(ShortArray(512) { 2 }) { emitted += it }

        assertEquals(1, emitted.size)
        assertEquals(List(512) { 2.toShort() }, emitted.single().toList())
    }
}
