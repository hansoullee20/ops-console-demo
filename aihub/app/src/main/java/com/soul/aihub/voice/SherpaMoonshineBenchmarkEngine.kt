package com.soul.aihub.voice

import android.content.res.AssetManager
import android.os.SystemClock
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.getFeatureConfig
import com.k2fsa.sherpa.onnx.getOfflineModelConfig

/**
 * Utterance-scoped sherpa-onnx Moonshine v2 adapter for same-PCM benchmarking.
 *
 * Moonshine v2 is an offline recognizer that sherpa combines with VAD to provide a
 * real-time/simulated-streaming user experience. This adapter therefore buffers one
 * bounded utterance and decodes it at [finish]. It intentionally emits no partials.
 *
 * It never owns or opens a microphone. Pre-roll and live PCM are supplied by Okja's
 * single-owner audio pipeline through [StreamingAsrEngine].
 */
class SherpaMoonshineBenchmarkEngine(
    assetManager: AssetManager,
    private val sampleRateHz: Int = 16_000,
    private val modelType: Int = KOREAN_MOONSHINE_TINY_MODEL_TYPE,
    maxUtteranceSeconds: Int = DEFAULT_MAX_UTTERANCE_SECONDS,
    private val nowElapsedRealtimeNs: () -> Long = { SystemClock.elapsedRealtimeNanos() },
) : StreamingAsrEngine {
    private val recognizer: OfflineRecognizer
    private val pcm: Pcm16UtteranceBuffer
    private var begun = false
    private var closed = false

    var lastDecodeMs: Double? = null
        private set
    var lastFinalizeMs: Double? = null
        private set

    init {
        require(sampleRateHz == 16_000) { "Okja Moonshine benchmark currently requires 16 kHz PCM" }
        require(maxUtteranceSeconds in 1..30) { "maxUtteranceSeconds must be within 1..30" }

        val modelConfig = requireNotNull(getOfflineModelConfig(type = modelType)) {
            "Unknown sherpa offline model type: $modelType"
        }
        val config = OfflineRecognizerConfig(
            featConfig = getFeatureConfig(sampleRate = sampleRateHz, featureDim = 80),
            modelConfig = modelConfig,
            decodingMethod = "greedy_search",
        )
        recognizer = OfflineRecognizer(assetManager = assetManager, config = config)
        pcm = Pcm16UtteranceBuffer(maxSamples = sampleRateHz * maxUtteranceSeconds)
    }

    override fun begin(preRollPcm16: ShortArray) {
        check(!closed) { "engine is closed" }
        pcm.begin(preRollPcm16)
        begun = true
        lastDecodeMs = null
        lastFinalizeMs = null
    }

    override fun accept(frame: PcmFrame): AsrUpdate? {
        check(!closed) { "engine is closed" }
        check(begun) { "begin() must be called before accept()" }
        pcm.append(frame.samples)
        return null
    }

    override fun finish(): AsrUpdate? {
        check(!closed) { "engine is closed" }
        check(begun) { "begin() must be called before finish()" }

        val samples = pcm.snapshot()
        val text = if (samples.isEmpty()) {
            lastDecodeMs = 0.0
            lastFinalizeMs = 0.0
            ""
        } else {
            val normalized = FloatArray(samples.size) { index -> samples[index] / 32768.0f }
            val stream = recognizer.createStream()
            try {
                stream.acceptWaveform(normalized, sampleRate = sampleRateHz)
                val decodeStart = nowElapsedRealtimeNs()
                recognizer.decode(stream)
                lastDecodeMs = (nowElapsedRealtimeNs() - decodeStart) / 1_000_000.0
                val finalizeStart = nowElapsedRealtimeNs()
                val result = recognizer.getResult(stream).text
                lastFinalizeMs = (nowElapsedRealtimeNs() - finalizeStart) / 1_000_000.0
                result
            } finally {
                stream.release()
            }
        }

        begun = false
        return AsrUpdate(
            text = text,
            isFinal = true,
            producedAtElapsedRealtimeNs = nowElapsedRealtimeNs(),
        )
    }

    override fun reset() {
        check(!closed) { "engine is closed" }
        pcm.reset()
        begun = false
        lastDecodeMs = null
        lastFinalizeMs = null
    }

    override fun close() {
        if (closed) return
        closed = true
        begun = false
        pcm.reset()
        recognizer.release()
    }

    companion object {
        /** sherpa-onnx helper index for sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27. */
        const val KOREAN_MOONSHINE_TINY_MODEL_TYPE = 51
        const val DEFAULT_MAX_UTTERANCE_SECONDS = 8
    }
}
