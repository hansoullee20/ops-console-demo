package com.soul.aihub.voice

/**
 * Deterministic replay harness for comparing StreamingAsrEngine implementations
 * against the exact same PCM sample stream.
 *
 * The harness does not acquire the microphone. It converts one recorded PCM16
 * case into canonical 20 ms PcmFrames and replays those frames to each engine.
 */
data class RecordedPcmCase(
    val id: String,
    val pcm16: ShortArray,
    val expectedTranscript: String? = null,
    val expectedCommandSuffix: String? = null,
    val sampleRateHz: Int = 16_000,
    val preRollSamples: Int = 0,
) {
    init {
        require(id.isNotBlank()) { "id must not be blank" }
        require(sampleRateHz == 16_000) { "Okja benchmark input must be 16 kHz" }
        require(preRollSamples >= 0) { "preRollSamples must be non-negative" }
        require(preRollSamples <= pcm16.size) { "preRollSamples exceeds PCM length" }
    }
}

data class AsrBenchmarkResult(
    val caseId: String,
    val engineName: String,
    val finalTranscript: String,
    val commandSuffixPreserved: Boolean?,
    val firstPartialLatencyMs: Long?,
    val finalLatencyMs: Long?,
    val discontinuityDetected: Boolean,
    val updateCount: Int,
)

class AsrBenchmarkHarness(
    private val frameSamples: Int = 320,
    private val frameDurationNs: Long = 20_000_000L,
) {
    init {
        require(frameSamples > 0) { "frameSamples must be positive" }
        require(frameDurationNs > 0) { "frameDurationNs must be positive" }
    }

    fun run(
        case: RecordedPcmCase,
        engineName: String,
        engine: StreamingAsrEngine,
    ): AsrBenchmarkResult {
        require(engineName.isNotBlank()) { "engineName must not be blank" }

        val preRoll = case.pcm16.copyOfRange(0, case.preRollSamples)
        val live = case.pcm16.copyOfRange(case.preRollSamples, case.pcm16.size)
        val continuity = PcmContinuityTracker()
        val updates = mutableListOf<AsrUpdate>()
        var firstPartialAtNs: Long? = null
        var finalAtNs: Long? = null
        var discontinuityDetected = false

        engine.reset()
        engine.begin(preRoll)

        try {
            var offset = 0
            var sequence = 0L
            while (offset < live.size) {
                val end = minOf(offset + frameSamples, live.size)
                val samples = live.copyOfRange(offset, end)
                val frame = PcmFrame(
                    samples = samples,
                    capturedAtElapsedRealtimeNs = sequence * frameDurationNs,
                    sequence = sequence,
                    startSampleIndex = case.preRollSamples.toLong() + offset.toLong(),
                )

                if (!continuity.observe(frame).continuous) discontinuityDetected = true
                engine.accept(frame)?.let { update ->
                    updates += update
                    if (!update.isFinal && firstPartialAtNs == null) {
                        firstPartialAtNs = update.producedAtElapsedRealtimeNs
                    }
                    if (update.isFinal) finalAtNs = update.producedAtElapsedRealtimeNs
                }

                offset = end
                sequence += 1
            }

            engine.finish()?.let { update ->
                updates += update
                if (!update.isFinal && firstPartialAtNs == null) {
                    firstPartialAtNs = update.producedAtElapsedRealtimeNs
                }
                if (update.isFinal) finalAtNs = update.producedAtElapsedRealtimeNs
            }
        } finally {
            engine.close()
        }

        val finalTranscript = updates.lastOrNull { it.isFinal }?.text
            ?: updates.lastOrNull()?.text.orEmpty()
        val suffixPreserved = case.expectedCommandSuffix?.let { suffix ->
            normalize(finalTranscript).contains(normalize(suffix))
        }

        return AsrBenchmarkResult(
            caseId = case.id,
            engineName = engineName,
            finalTranscript = finalTranscript,
            commandSuffixPreserved = suffixPreserved,
            firstPartialLatencyMs = firstPartialAtNs?.div(1_000_000L),
            finalLatencyMs = finalAtNs?.div(1_000_000L),
            discontinuityDetected = discontinuityDetected,
            updateCount = updates.size,
        )
    }

    private fun normalize(text: String): String =
        text.lowercase().replace(Regex("\\s+"), " ").trim()
}
