package com.soul.aihub.voice

/**
 * Converts one complete 80 ms / 1280-sample PCM16 window into one openWakeWord
 * embedding frame. The concrete implementation may use ONNX/TFLite but must never
 * own or acquire the microphone.
 */
interface OpenWakeWordEmbeddingFrontend : AutoCloseable {
    val embeddingDim: Int
    fun embed(pcm16: ShortArray): FloatArray
    fun reset() = Unit
    override fun close() = Unit
}

/**
 * Scores a contiguous, oldest-to-newest sequence of embedding frames.
 * [features] is flattened row-major with size [inputFrames] * [embeddingDim].
 */
interface OpenWakeWordEmbeddingClassifier : AutoCloseable {
    val inputFrames: Int
    val embeddingDim: Int
    fun score(features: FloatArray): Float
    fun reset() = Unit
    override fun close() = Unit
}

/**
 * Stateful openWakeWord predictor core for Android caller-owned PCM.
 *
 * Unlike openWakeWord 0.6.0's Python AudioFeatures initialization, this production
 * core does not synthesize random history. It remains fail-closed until the
 * classifier has a complete history of real contiguous PCM-derived embeddings.
 * This makes startup and post-discontinuity behavior deterministic and prevents
 * seeded/synthetic context from authorizing a wake. Exact Python compatibility
 * replay remains a separate benchmark surface.
 */
class OpenWakeWordStreamingPredictor(
    override val modelName: String,
    private val frontend: OpenWakeWordEmbeddingFrontend,
    private val classifier: OpenWakeWordEmbeddingClassifier,
    private val inferenceWindowSamples: Int = OpenWakeWordPcmWakeDetector.DEFAULT_INFERENCE_WINDOW_SAMPLES,
) : OpenWakeWordFramePredictor {
    init {
        require(modelName.isNotBlank()) { "modelName must not be blank" }
        require(inferenceWindowSamples > 0) { "inferenceWindowSamples must be positive" }
        require(frontend.embeddingDim > 0) { "frontend embeddingDim must be positive" }
        require(classifier.inputFrames > 0) { "classifier inputFrames must be positive" }
        require(classifier.embeddingDim == frontend.embeddingDim) {
            "classifier/frontend embedding dimension mismatch"
        }
    }

    private val history = ArrayDeque<FloatArray>(classifier.inputFrames)
    private var closed = false

    override fun predict(pcm16: ShortArray): Float {
        check(!closed) { "predictor is closed" }
        require(pcm16.size == inferenceWindowSamples) {
            "expected $inferenceWindowSamples PCM samples, got ${pcm16.size}"
        }

        val embedding = frontend.embed(pcm16)
        require(embedding.size == frontend.embeddingDim) {
            "frontend returned ${embedding.size} values, expected ${frontend.embeddingDim}"
        }
        require(embedding.all(Float::isFinite)) { "frontend returned non-finite embedding" }

        if (history.size == classifier.inputFrames) history.removeFirst()
        history.addLast(embedding.copyOf())

        // Fail closed while the model lacks a complete real-audio context window.
        if (history.size < classifier.inputFrames) return 0.0f

        val flattened = FloatArray(classifier.inputFrames * classifier.embeddingDim)
        var offset = 0
        for (frame in history) {
            frame.copyInto(flattened, destinationOffset = offset)
            offset += classifier.embeddingDim
        }

        val score = classifier.score(flattened)
        require(score.isFinite() && score in 0.0f..1.0f) {
            "classifier returned invalid score: $score"
        }
        return score
    }

    override fun reset() {
        check(!closed) { "predictor is closed" }
        history.clear()
        frontend.reset()
        classifier.reset()
    }

    override fun close() {
        if (closed) return
        closed = true
        history.clear()
        // Close both even if one implementation throws on close in a future native binding.
        var firstFailure: Throwable? = null
        try {
            frontend.close()
        } catch (t: Throwable) {
            firstFailure = t
        }
        try {
            classifier.close()
        } catch (t: Throwable) {
            if (firstFailure == null) firstFailure = t else firstFailure.addSuppressed(t)
        }
        firstFailure?.let { throw it }
    }
}
