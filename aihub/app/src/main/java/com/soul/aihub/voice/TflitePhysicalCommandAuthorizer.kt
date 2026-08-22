package com.soul.aihub.voice

import android.content.Context
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.tflite.java.TfLite
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.tensorflow.lite.InterpreterApi
import org.tensorflow.lite.InterpreterApi.Options.TfLiteRuntime
import java.io.FileInputStream
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel

/** Calibrated safety thresholds. Values must come from held-out data, never from guesswork. */
data class PhysicalCommandThresholds(
    val minConfidence: Float,
    val minTopTwoMargin: Float,
    val minOppositeActionMargin: Float,
) {
    init {
        require(minConfidence in 0f..1f) { "minConfidence must be in [0, 1]" }
        require(minTopTwoMargin in 0f..1f) { "minTopTwoMargin must be in [0, 1]" }
        require(minOppositeActionMargin in 0f..1f) { "minOppositeActionMargin must be in [0, 1]" }
    }
}

/**
 * Five-class raw-PCM physical-command authorizer backed by a TFLite model.
 *
 * Input contract: float32 [1, 48000], 16 kHz mono PCM normalized to [-1, 1]. The model class order
 * is fixed by [PhysicalCommandScorePolicy.CLASS_ORDER]. Output is five logits.
 *
 * The interpreter uses the LiteRT runtime supplied by Google Play services rather than packaging a
 * second ONNX Runtime into the APK. If initialization/inference fails, VoiceSessionController treats
 * the authorizer as unavailable and physical commands fail closed.
 *
 * Until endpointing is calibrated, capture is allowed to accumulate beyond the model window so an
 * overlong utterance can be reported as an explicit abstention rather than throwing mid-stream. We
 * never silently crop an overlong physical command because cropping could remove the target/action.
 */
class TflitePhysicalCommandAuthorizer private constructor(
    private val interpreter: InterpreterApi,
    private val thresholds: PhysicalCommandThresholds,
    private val minimumSamples: Int,
) : PhysicalCommandAuthorizer {
    private val pcm = Pcm16UtteranceBuffer(MAX_CAPTURE_SAMPLES)
    private var closed = false

    init {
        require(minimumSamples in 1..INPUT_SAMPLES) {
            "minimumSamples must be in 1..$INPUT_SAMPLES"
        }
    }

    override fun reset() {
        check(!closed) { "authorizer is closed" }
        pcm.reset()
    }

    override fun begin(preRollPcm16: ShortArray) {
        check(!closed) { "authorizer is closed" }
        pcm.begin(preRollPcm16)
    }

    override fun accept(frame: PcmFrame) {
        check(!closed) { "authorizer is closed" }
        pcm.append(frame.samples)
    }

    override fun finish(): PhysicalCommandDecision {
        check(!closed) { "authorizer is closed" }
        val samples = pcm.snapshot()
        if (samples.size < minimumSamples) {
            return PhysicalCommandDecision.Abstain(
                "physical-command audio too short: ${samples.size} < $minimumSamples samples",
            )
        }
        if (samples.size > INPUT_SAMPLES) {
            return PhysicalCommandDecision.Abstain(
                "physical-command audio exceeds qualified model window: " +
                    "${samples.size} > $INPUT_SAMPLES samples",
            )
        }

        val input = Array(1) { FloatArray(INPUT_SAMPLES) }
        samples.forEachIndexed { index, sample ->
            input[0][index] = sample.toFloat() / 32768.0f
        }
        val output = Array(1) { FloatArray(PhysicalCommandScorePolicy.CLASS_ORDER.size) }
        interpreter.run(input, output)

        return PhysicalCommandScorePolicy.decide(
            logits = output[0],
            thresholds = thresholds,
        )
    }

    override fun close() {
        if (closed) return
        closed = true
        pcm.reset()
        interpreter.close()
    }

    companion object {
        const val INPUT_SAMPLES = 48_000
        const val SAMPLE_RATE_HZ = 16_000
        const val MAX_CAPTURE_SAMPLES = SAMPLE_RATE_HZ * 8

        /**
         * Initializes the Google Play services LiteRT module off the UI thread, memory-maps the model
         * asset, and returns an authorizer. A missing/unavailable system module throws so the caller can
         * keep RejectingPhysicalCommandAuthorizer active.
         */
        suspend fun createFromAsset(
            context: Context,
            assetName: String,
            thresholds: PhysicalCommandThresholds,
            minimumSamples: Int = SAMPLE_RATE_HZ / 2,
        ): TflitePhysicalCommandAuthorizer = withContext(Dispatchers.IO) {
            Tasks.await(TfLite.initialize(context.applicationContext))
            val model = mapAsset(context, assetName)
            val options = InterpreterApi.Options()
                .setRuntime(TfLiteRuntime.FROM_SYSTEM_ONLY)
            val interpreter = InterpreterApi.create(model, options)
            TflitePhysicalCommandAuthorizer(interpreter, thresholds, minimumSamples)
        }

        private fun mapAsset(context: Context, assetName: String): MappedByteBuffer {
            context.assets.openFd(assetName).use { descriptor ->
                FileInputStream(descriptor.fileDescriptor).use { input ->
                    return input.channel.map(
                        FileChannel.MapMode.READ_ONLY,
                        descriptor.startOffset,
                        descriptor.declaredLength,
                    )
                }
            }
        }
    }
}
