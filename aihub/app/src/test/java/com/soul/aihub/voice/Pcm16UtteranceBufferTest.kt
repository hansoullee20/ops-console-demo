package com.soul.aihub.voice

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class Pcm16UtteranceBufferTest {
    @Test
    fun preservesPreRollThenLivePcmInOrder() {
        val buffer = Pcm16UtteranceBuffer(maxSamples = 16)

        buffer.begin(shortArrayOf(1, 2, 3))
        buffer.append(shortArrayOf(4, 5))
        buffer.append(shortArrayOf(6, 7, 8))

        assertEquals(8, buffer.sampleCount())
        assertArrayEquals(shortArrayOf(1, 2, 3, 4, 5, 6, 7, 8), buffer.snapshot())
    }

    @Test
    fun beginStartsANewUtterance() {
        val buffer = Pcm16UtteranceBuffer(maxSamples = 8)
        buffer.begin(shortArrayOf(1, 2, 3))
        buffer.append(shortArrayOf(4))

        buffer.begin(shortArrayOf(9, 10))

        assertArrayEquals(shortArrayOf(9, 10), buffer.snapshot())
    }

    @Test(expected = IllegalArgumentException::class)
    fun overflowFailsClosedInsteadOfTruncating() {
        val buffer = Pcm16UtteranceBuffer(maxSamples = 4)
        buffer.begin(shortArrayOf(1, 2, 3))

        buffer.append(shortArrayOf(4, 5))
    }
}
