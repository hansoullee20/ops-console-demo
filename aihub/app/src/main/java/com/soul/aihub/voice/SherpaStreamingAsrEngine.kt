package com.soul.aihub.voice

import android.content.res.AssetManager
import android.os.SystemClock
import com.k2fsa.sherpa.onnx.OnlineRecognizer
import com.k2fsa.sherpa.onnx.OnlineRecognizerConfig
import com.k2fsa.sherpa.onnx.OnlineStream
import com.k2fsa.sherpa.onnx.getEndpointConfig
import com.k2fsa.sherpa.onnx.getFeatureConfig
import com.k2fsa.sherpa.onnx.getModelConfig

/**
 * PCM-fed sherpa-onnx streaming adapter for the Okja StreamingAsrEngine contract.
 *
 * This adapter never opens AudioRecord. Model assets are expected to be packaged
 * separately under the sherpa model directory selected by [modelType].
 */
class SherpaStreamingAsrEngine(
    assetManager: AssetManager,
    private val sampleRateHz: Int = 16_000,
    private val modelType: Int = KOREAN_STREAMING_ZIPFORMER_MODEL_TYPE,
    private val nowElapsedRealtimeNs: () -> Long = { SystemClock.elapsedRealtimeNanos() },
) : StreamingAsrEngine {
    private val recognizer: OnlineRecognizer
    private var stream: OnlineStream? = null
    private var lastText: String = ""

    init {
        require(sampleRateHz == 16_000) { "Okja sherpa adapter currently requires 16 kHz PCM" }
        val modelConfig = requireNotNull(getModelConfig(type = modelType)) {
            "Unknown sherpa online model type: $modelType"
        }
        val config = OnlineRecognizerConfig(
            featConfig = getFeatureConfig(sampleRate = sampleRateHz, featureDim = 80),
            modelConfig = modelConfig,
            endpointConfig = getEndpointConfig(),
            enableEndpoint = false,
        )
        recognizer = OnlineRecognizer(assetManager = assetManager, config = config)
    }

    override fun begin(preRollPcm16: ShortArray) {
        releaseStream()
        lastText = ""
        stream = recognizer.createStream()
        if (preRollPcm16.isNotEmpty()) {
            acceptSamples(preRollPcm16)
            decodeReady()
            lastText = currentText()
        }
    }

    override fun accept(frame: PcmFrame): AsrUpdate? {
        checkNotNull(stream) { "begin() must be called before accept()" }
        if (frame.samples.isEmpty()) return null

        acceptSamples(frame.samples)
        decodeReady()
        val text = currentText()
        if (text == lastText) return null

        lastText = text
        return AsrUpdate(
            text = text,
            isFinal = false,
            producedAtElapsedRealtimeNs = nowElapsedRealtimeNs(),
        )
    }

    override fun finish(): AsrUpdate? {
        val active = stream ?: return null
        active.inputFinished()
        decodeReady()
        val text = currentText()
        lastText = text
        return AsrUpdate(
            text = text,
            isFinal = true,
            producedAtElapsedRealtimeNs = nowElapsedRealtimeNs(),
        )
    }

    override fun reset() {
        releaseStream()
        lastText = ""
    }

    override fun close() {
        releaseStream()
        recognizer.release()
    }

    private fun acceptSamples(samples: ShortArray) {
        val active = checkNotNull(stream)
        val normalized = FloatArray(samples.size) { index -> samples[index] / 32768.0f }
        active.acceptWaveform(normalized, sampleRate = sampleRateHz)
    }

    private fun decodeReady() {
        val active = checkNotNull(stream)
        while (recognizer.isReady(active)) {
            recognizer.decode(active)
        }
    }

    private fun currentText(): String {
        val active = checkNotNull(stream)
        return recognizer.getResult(active).text
    }

    private fun releaseStream() {
        stream?.release()
        stream = null
    }

    companion object {
        /** Official sherpa-onnx helper index for the Korean streaming Zipformer 2024-06-16 model. */
        const val KOREAN_STREAMING_ZIPFORMER_MODEL_TYPE = 14
    }
}
