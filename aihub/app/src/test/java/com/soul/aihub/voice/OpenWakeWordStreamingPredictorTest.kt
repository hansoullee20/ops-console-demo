package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class OpenWakeWordStreamingPredictorTest {
    private class FakeFrontend(
        override val embeddingDim: Int = 2,
    ) : OpenWakeWordEmbeddingFrontend {
        var resetCount = 0
        var closeCount = 0

        override fun embed(pcm16: ShortArray): FloatArray {
            val first = pcm16.firstOrNull()?.toFloat() ?: 0.0f
            val last = pcm16.lastOrNull()?.toFloat() ?: 0.0f
            return floatArrayOf(first, last)
        }

        override fun reset() {
            resetCount += 1
        }

        override fun close() {
            closeCount += 1
        }
    }

    private class FakeClassifier(
        override val inputFrames: Int = 3,
        override val embeddingDim: Int = 2,
    ) : OpenWakeWordEmbeddingClassifier {
        val inputs = mutableListOf<FloatArray>()
        var resetCount = 0
        var closeCount = 0
        var nextScore = 0.75f

        override fun score(features: FloatArray): Float {
            inputs += features.copyOf()
            return nextScore
        }

        override fun reset() {
            resetCount += 1
        }

        override fun close() {
            closeCount += 1
        }
    }

    private fun pcm(value: Short): ShortArray =
        ShortArray(OpenWakeWordPcmWakeDetector.DEFAULT_INFERENCE_WINDOW_SAMPLES) { value }

    @Test
    fun staysFailClosedUntilFullRealAudioHistoryExists() {
        val frontend = FakeFrontend()
        val classifier = FakeClassifier(inputFrames = 3)
        val predictor = OpenWakeWordStreamingPredictor("okja", frontend, classifier)

        assertEquals(0.0f, predictor.predict(pcm(1)), 0.0f)
        assertEquals(0.0f, predictor.predict(pcm(2)), 0.0f)
        assertTrue(classifier.inputs.isEmpty())

        assertEquals(0.75f, predictor.predict(pcm(3)), 0.0f)
        assertEquals(1, classifier.inputs.size)
        assertTrue(
            classifier.inputs.single().contentEquals(
                floatArrayOf(1f, 1f, 2f, 2f, 3f, 3f),
            ),
        )
    }

    @Test
    fun rollingHistoryPreservesOldestToNewestOrder() {
        val classifier = FakeClassifier(inputFrames = 2)
        val predictor = OpenWakeWordStreamingPredictor("okja", FakeFrontend(), classifier)

        predictor.predict(pcm(10))
        predictor.predict(pcm(20))
        predictor.predict(pcm(30))

        assertEquals(2, classifier.inputs.size)
        assertTrue(classifier.inputs[0].contentEquals(floatArrayOf(10f, 10f, 20f, 20f)))
        assertTrue(classifier.inputs[1].contentEquals(floatArrayOf(20f, 20f, 30f, 30f)))
    }

    @Test
    fun resetClearsHistoryAndRequiresFreshRealAudioWarmup() {
        val frontend = FakeFrontend()
        val classifier = FakeClassifier(inputFrames = 2)
        val predictor = OpenWakeWordStreamingPredictor("okja", frontend, classifier)

        predictor.predict(pcm(1))
        predictor.predict(pcm(2))
        assertEquals(1, classifier.inputs.size)

        predictor.reset()
        assertEquals(1, frontend.resetCount)
        assertEquals(1, classifier.resetCount)

        assertEquals(0.0f, predictor.predict(pcm(3)), 0.0f)
        assertEquals(1, classifier.inputs.size)
        predictor.predict(pcm(4))
        assertEquals(2, classifier.inputs.size)
        assertTrue(classifier.inputs.last().contentEquals(floatArrayOf(3f, 3f, 4f, 4f)))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsWrongPcmWindowSize() {
        val predictor = OpenWakeWordStreamingPredictor(
            "okja",
            FakeFrontend(),
            FakeClassifier(inputFrames = 1),
        )
        predictor.predict(ShortArray(320))
    }

    @Test
    fun closeReleasesBothModelStagesExactlyOnce() {
        val frontend = FakeFrontend()
        val classifier = FakeClassifier()
        val predictor = OpenWakeWordStreamingPredictor("okja", frontend, classifier)

        predictor.close()
        predictor.close()

        assertEquals(1, frontend.closeCount)
        assertEquals(1, classifier.closeCount)
    }
}
