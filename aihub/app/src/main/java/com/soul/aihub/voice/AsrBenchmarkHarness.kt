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

    val expectsRecognition: Boolean
        get() = !expectedTranscript.isNullOrBlank() || !expectedCommandSuffix.isNullOrBlank()
}

data class AsrBenchmarkResult(
    val caseId: String,
    val engineName: String,
    val finalTranscript: String,
    val transcriptMatchesExpected: Boolean?,
    val commandSuffixPreserved: Boolean?,
    val firstPartialLatencyMs: Long?,
    val finalLatencyMs: Long?,
    val discontinuityDetected: Boolean,
    val recognitionExpectedButEmpty: Boolean,
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
        captureStartElapsedRealtimeNs: Long = 0L,
    ): AsrBenchmarkResult {
        require(engineName.isNotBlank()) { "engineName must not be blank" }
        require(captureStartElapsedRealtimeNs >= 0L) { "captureStartElapsedRealtimeNs must be non-negative" }

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
                    capturedAtElapsedRealtimeNs = captureStartElapsedRealtimeNs + sequence * frameDurationNs,
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
        val transcriptMatch = case.expectedTranscript?.let { expected ->
            normalizeTranscript(finalTranscript) == normalizeTranscript(expected)
        }
        val suffixPreserved = case.expectedCommandSuffix?.let { suffix ->
            normalizeCommand(finalTranscript).contains(normalizeCommand(suffix))
        }

        return AsrBenchmarkResult(
            caseId = case.id,
            engineName = engineName,
            finalTranscript = finalTranscript,
            transcriptMatchesExpected = transcriptMatch,
            commandSuffixPreserved = suffixPreserved,
            firstPartialLatencyMs = latencyMs(firstPartialAtNs, captureStartElapsedRealtimeNs),
            finalLatencyMs = latencyMs(finalAtNs, captureStartElapsedRealtimeNs),
            discontinuityDetected = discontinuityDetected,
            recognitionExpectedButEmpty = case.expectsRecognition && finalTranscript.isBlank(),
            updateCount = updates.size,
        )
    }

    private fun latencyMs(producedAtNs: Long?, startAtNs: Long): Long? {
        if (producedAtNs == null || producedAtNs < startAtNs) return null
        return (producedAtNs - startAtNs) / 1_000_000L
    }

    /**
     * Transcript fidelity stays intentionally conservative: case/punctuation/spacing
     * differences are ignored, but lexical substitutions still count as recognition errors.
     */
    private fun normalizeTranscript(text: String): String =
        text.lowercase()
            .replace(Regex("[\\p{P}\\p{S}]+"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()

    /**
     * Device-command continuity is semantic rather than orthographic. A recognizer may
     * emit common Korean spoken spellings for Latin device names (for example `TV` ->
     * `티비`) without losing the command. Keep this alias list deliberately tiny and
     * command-domain-specific so genuinely different verbs/targets still fail.
     */
    private fun normalizeCommand(text: String): String =
        normalizeTranscript(text)
            .replace("텔레비전", "tv")
            .replace("티브이", "tv")
            .replace("티비", "tv")
            .replace("t v", "tv")
            .replace(Regex("\\s+"), "")
}
