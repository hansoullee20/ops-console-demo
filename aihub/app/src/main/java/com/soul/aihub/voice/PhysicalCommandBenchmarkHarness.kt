package com.soul.aihub.voice

/** One frozen PCM case for safety-oriented physical-command evaluation. */
data class RecordedPhysicalCommandCase(
    val id: String,
    val pcm16: ShortArray,
    val expected: PhysicalCommandClass,
    val sampleRateHz: Int = 16_000,
    val preRollSamples: Int = 0,
) {
    init {
        require(id.isNotBlank()) { "id must not be blank" }
        require(sampleRateHz == 16_000) { "Okja command benchmark input must be 16 kHz" }
        require(preRollSamples >= 0) { "preRollSamples must be non-negative" }
        require(preRollSamples <= pcm16.size) { "preRollSamples exceeds PCM length" }
    }
}

data class PhysicalCommandBenchmarkResult(
    val caseId: String,
    val engineName: String,
    val decision: PhysicalCommandDecision,
    val outcome: PhysicalCommandOutcome,
    val oppositeActionInversion: Boolean,
    val discontinuityDetected: Boolean,
)

/**
 * Deterministic same-PCM replay for acoustic physical-command authorizers.
 *
 * The harness never acquires a microphone and deliberately reports semantic safety failures rather
 * than transcript WER/CER. A production gate can aggregate these records into correct/abstain,
 * wrong-device, wrong-action/inversion, and false-physical-execution counts.
 */
class PhysicalCommandBenchmarkHarness(
    private val frameSamples: Int = 320,
    private val frameDurationNs: Long = 20_000_000L,
) {
    init {
        require(frameSamples > 0) { "frameSamples must be positive" }
        require(frameDurationNs > 0) { "frameDurationNs must be positive" }
    }

    fun run(
        case: RecordedPhysicalCommandCase,
        engineName: String,
        authorizer: PhysicalCommandAuthorizer,
        captureStartElapsedRealtimeNs: Long = 0L,
    ): PhysicalCommandBenchmarkResult {
        require(engineName.isNotBlank()) { "engineName must not be blank" }
        require(captureStartElapsedRealtimeNs >= 0L) { "captureStartElapsedRealtimeNs must be non-negative" }

        val preRoll = case.pcm16.copyOfRange(0, case.preRollSamples)
        val live = case.pcm16.copyOfRange(case.preRollSamples, case.pcm16.size)
        val continuity = PcmContinuityTracker()
        var discontinuityDetected = false

        authorizer.reset()
        authorizer.begin(preRoll)

        val decision = try {
            var offset = 0
            var sequence = 0L
            while (offset < live.size) {
                val end = minOf(offset + frameSamples, live.size)
                val frame = PcmFrame(
                    samples = live.copyOfRange(offset, end),
                    capturedAtElapsedRealtimeNs = captureStartElapsedRealtimeNs + sequence * frameDurationNs,
                    sequence = sequence,
                    startSampleIndex = case.preRollSamples.toLong() + offset.toLong(),
                )
                if (!continuity.observe(frame).continuous) discontinuityDetected = true
                authorizer.accept(frame)
                offset = end
                sequence += 1L
            }
            authorizer.finish()
        } finally {
            authorizer.close()
        }

        val evaluation = PhysicalCommandSafetyEvaluator.evaluate(case.expected, decision)
        return PhysicalCommandBenchmarkResult(
            caseId = case.id,
            engineName = engineName,
            decision = decision,
            outcome = evaluation.outcome,
            oppositeActionInversion = evaluation.oppositeActionInversion,
            discontinuityDetected = discontinuityDetected,
        )
    }
}
