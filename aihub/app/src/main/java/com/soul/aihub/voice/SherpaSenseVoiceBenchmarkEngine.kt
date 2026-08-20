package com.soul.aihub.voice

import android.content.res.AssetManager
import android.os.SystemClock
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.getFeatureConfig
import com.k2fsa.sherpa.onnx.getOfflineModelConfig

/**
 * Utterance-scoped sherpa-onnx SenseVoice adapter for same-PCM benchmarking.
 *
 * Uses the official multilingual int8 model that includes Korean. The engine buffers
 * one bounded utterance and emits one final result. It never owns or opens a microphone;
 * all PCM comes from Okja's single-owner AudioEngine path.
 */
class SherpaSenseVoiceBenchmarkEngine(
    assetManager: AssetManager,
    private val sampleRateHz: Int = 16_000,
    private val modelType: Int = KOREAN_SENSEVOICE_MODEL_TYPE,
    maxUtteranceSeconds: Int = DEFAULT_MAX_UTTERANCE_SECONDS,
    private val nowElapsedRealtimeNs: () -> Long = { SystemClock.elapsedRealtimeNanos() },
) : StreamingAsrEngine {
    private val recognizer: OfflineRecognizer
    private val pcm: Pcm16UtteranceBuffer
    private var begun = false
    private var closed = false

    init {
        require(sampleRateHz == 16_000) { "Okja SenseVoice benchmark currently requires 16 kHz PCM" }
        require(maxUtteranceSeconds in 1..30) { "maxUtteranceSeconds must be within 1..30" }

        val modelConfig = requireNotNull(getOfflineModelConfig(type = modelType)) {
            "Unknown sherpa offline model type: $modelType"
        }
        // This benchmark corpus is Korean-only. Pin the language instead of paying for
        // automatic language detection, and keep ITN disabled so command wording is
        // scored against the recognizer's direct Korean text rather than a formatter.
        modelConfig.senseVoice.language = "ko"
        modelConfig.senseVoice.useInverseTextNormalization = false

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
            ""
        } else {
            val normalized = FloatArray(samples.size) { index -> samples[index] / 32768.0f }
            val stream = recognizer.createStream()
            try {
                stream.acceptWaveform(normalized, sampleRate = sampleRateHz)
                recognizer.decode(stream)
                recognizer.getResult(stream).text
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
    }

    override fun close() {
        if (closed) return
        closed = true
        begun = false
        pcm.reset()
        recognizer.release()
    }

    companion object {
        /** sherpa-onnx v1.13.4 helper index for the 2025-09-09 multilingual SenseVoice int8 model. */
        const val KOREAN_SENSEVOICE_MODEL_TYPE = 41
        const val DEFAULT_MAX_UTTERANCE_SECONDS = 8
    }
}
