package com.soul.aihub.voice

/**
 * One intentional wake occurrence inside recorded PCM.
 *
 * [keywordEndSampleIndex] is the sample immediately after the spoken wake phrase.
 * Matching is performed in sample time, not wall-clock time, so offline replay is
 * deterministic even when a detector internally timestamps results with SystemClock.
 */
data class ExpectedWake(
    val keyword: String,
    val keywordEndSampleIndex: Long,
    val matchEarlyMs: Int = 200,
    val matchLateMs: Int = 1_000,
) {
    init {
        require(keyword.isNotBlank()) { "keyword must not be blank" }
        require(keywordEndSampleIndex >= 0L) { "keywordEndSampleIndex must be non-negative" }
        require(matchEarlyMs >= 0) { "matchEarlyMs must be non-negative" }
        require(matchLateMs >= 0) { "matchLateMs must be non-negative" }
    }
}

/** Recorded PCM used to benchmark one microphone-free WakeDetector. */
data class WakeBenchmarkCase(
    val id: String,
    val pcm16: ShortArray,
    val expectedWakes: List<ExpectedWake> = emptyList(),
    val sampleRateHz: Int = 16_000,
) {
    init {
        require(id.isNotBlank()) { "id must not be blank" }
        require(sampleRateHz == 16_000) { "Okja wake benchmark input must be 16 kHz" }
        expectedWakes.forEach { expected ->
            require(expected.keywordEndSampleIndex <= pcm16.size.toLong()) {
                "expected wake exceeds PCM length"
            }
        }
    }

    val durationSeconds: Double
        get() = pcm16.size.toDouble() / sampleRateHz.toDouble()
}

data class WakeDetectionObservation(
    val keyword: String,
    val detectionSampleIndex: Long,
    val score: Float?,
    val matchedExpectedIndex: Int?,
    val latencyFromKeywordEndMs: Double?,
)

data class WakeBenchmarkResult(
    val caseId: String,
    val detectorName: String,
    val intentionalAttempts: Int,
    val detectedAttempts: Int,
    val misses: Int,
    val falseActivations: Int,
    val extraDetectionsDuringPositiveCase: Int,
    val recall: Double?,
    val negativeListeningHours: Double,
    val falseActivationsPerHour: Double?,
    val latenciesMs: List<Double>,
    val observations: List<WakeDetectionObservation>,
)

data class WakeBenchmarkAggregate(
    val caseCount: Int,
    val intentionalAttempts: Int,
    val detectedAttempts: Int,
    val misses: Int,
    val falseActivations: Int,
    val extraDetectionsDuringPositiveCases: Int,
    val recall: Double?,
    val negativeListeningHours: Double,
    val falseActivationsPerHour: Double?,
    val latencyP50Ms: Double?,
    val latencyP95Ms: Double?,
) {
    companion object {
        fun from(results: List<WakeBenchmarkResult>): WakeBenchmarkAggregate {
            val attempts = results.sumOf { it.intentionalAttempts }
            val detected = results.sumOf { it.detectedAttempts }
            val misses = results.sumOf { it.misses }
            val falseActivations = results.sumOf { it.falseActivations }
            val extra = results.sumOf { it.extraDetectionsDuringPositiveCase }
            val negativeHours = results.sumOf { it.negativeListeningHours }
            val latencies = results.flatMap { it.latenciesMs }.sorted()

            return WakeBenchmarkAggregate(
                caseCount = results.size,
                intentionalAttempts = attempts,
                detectedAttempts = detected,
                misses = misses,
                falseActivations = falseActivations,
                extraDetectionsDuringPositiveCases = extra,
                recall = if (attempts == 0) null else detected.toDouble() / attempts.toDouble(),
                negativeListeningHours = negativeHours,
                falseActivationsPerHour = if (negativeHours <= 0.0) {
                    null
                } else {
                    falseActivations.toDouble() / negativeHours
                },
                latencyP50Ms = percentile(latencies, 0.50),
                latencyP95Ms = percentile(latencies, 0.95),
            )
        }

        private fun percentile(sorted: List<Double>, fraction: Double): Double? {
            if (sorted.isEmpty()) return null
            if (sorted.size == 1) return sorted.first()
            val position = fraction * (sorted.size - 1).toDouble()
            val lower = position.toInt()
            val upper = minOf(lower + 1, sorted.lastIndex)
            val weight = position - lower.toDouble()
            return sorted[lower] * (1.0 - weight) + sorted[upper] * weight
        }
    }
}

/**
 * Deterministic same-PCM replay harness for wake detectors.
 *
 * The harness never opens the microphone. Detection position is defined as the end
 * sample index of the frame that produced a WakeDetection. This makes scoring stable
 * across detectors regardless of their internal wall-clock timestamp implementation.
 *
 * False-activations/hour is computed only from cases with no intentional wakes. This
 * avoids inflating the denominator with short positive utterance clips; positive cases
 * still report unmatched detections separately.
 */
class WakeBenchmarkHarness(
    private val frameSamples: Int = 320,
    private val frameDurationNs: Long = 20_000_000L,
) {
    init {
        require(frameSamples > 0) { "frameSamples must be positive" }
        require(frameDurationNs > 0L) { "frameDurationNs must be positive" }
    }

    fun run(
        case: WakeBenchmarkCase,
        detectorName: String,
        detector: WakeDetector,
        captureStartElapsedRealtimeNs: Long = 0L,
    ): WakeBenchmarkResult {
        require(detectorName.isNotBlank()) { "detectorName must not be blank" }
        require(captureStartElapsedRealtimeNs >= 0L) { "captureStartElapsedRealtimeNs must be non-negative" }

        val rawDetections = mutableListOf<RawWakeDetection>()

        try {
            var offset = 0
            var sequence = 0L
            while (offset < case.pcm16.size) {
                val end = minOf(offset + frameSamples, case.pcm16.size)
                val frame = PcmFrame(
                    samples = case.pcm16.copyOfRange(offset, end),
                    capturedAtElapsedRealtimeNs = captureStartElapsedRealtimeNs + sequence * frameDurationNs,
                    sequence = sequence,
                    startSampleIndex = offset.toLong(),
                )

                detector.accept(frame)?.let { detection ->
                    rawDetections += RawWakeDetection(
                        keyword = detection.keyword,
                        detectionSampleIndex = frame.endSampleIndexExclusive,
                        score = detection.score,
                    )
                }

                offset = end
                sequence += 1L
            }
        } finally {
            detector.close()
        }

        val unmatchedExpected = case.expectedWakes.indices.toMutableSet()
        val observations = rawDetections.map { detection ->
            val matchedIndex = bestMatch(case, detection, unmatchedExpected)
            val latencyMs = matchedIndex?.let { index ->
                val expected = case.expectedWakes[index]
                samplesToMs(
                    samples = detection.detectionSampleIndex - expected.keywordEndSampleIndex,
                    sampleRateHz = case.sampleRateHz,
                )
            }
            if (matchedIndex != null) unmatchedExpected.remove(matchedIndex)

            WakeDetectionObservation(
                keyword = detection.keyword,
                detectionSampleIndex = detection.detectionSampleIndex,
                score = detection.score,
                matchedExpectedIndex = matchedIndex,
                latencyFromKeywordEndMs = latencyMs,
            )
        }

        val attempts = case.expectedWakes.size
        val detectedAttempts = attempts - unmatchedExpected.size
        val isNegativeCase = attempts == 0
        val unmatchedDetectionCount = observations.count { it.matchedExpectedIndex == null }
        val negativeHours = if (isNegativeCase) case.durationSeconds / 3600.0 else 0.0
        val falseActivations = if (isNegativeCase) unmatchedDetectionCount else 0
        val extraPositiveDetections = if (isNegativeCase) 0 else unmatchedDetectionCount

        return WakeBenchmarkResult(
            caseId = case.id,
            detectorName = detectorName,
            intentionalAttempts = attempts,
            detectedAttempts = detectedAttempts,
            misses = unmatchedExpected.size,
            falseActivations = falseActivations,
            extraDetectionsDuringPositiveCase = extraPositiveDetections,
            recall = if (attempts == 0) null else detectedAttempts.toDouble() / attempts.toDouble(),
            negativeListeningHours = negativeHours,
            falseActivationsPerHour = if (negativeHours <= 0.0) {
                null
            } else {
                falseActivations.toDouble() / negativeHours
            },
            latenciesMs = observations.mapNotNull { it.latencyFromKeywordEndMs },
            observations = observations,
        )
    }

    private fun bestMatch(
        case: WakeBenchmarkCase,
        detection: RawWakeDetection,
        unmatchedExpected: Set<Int>,
    ): Int? {
        return unmatchedExpected
            .asSequence()
            .filter { index ->
                val expected = case.expectedWakes[index]
                if (expected.keyword != detection.keyword) return@filter false

                val earlySamples = msToSamples(expected.matchEarlyMs, case.sampleRateHz)
                val lateSamples = msToSamples(expected.matchLateMs, case.sampleRateHz)
                val earliest = maxOf(0L, expected.keywordEndSampleIndex - earlySamples)
                val latest = expected.keywordEndSampleIndex + lateSamples
                detection.detectionSampleIndex in earliest..latest
            }
            .minByOrNull { index ->
                kotlin.math.abs(
                    detection.detectionSampleIndex - case.expectedWakes[index].keywordEndSampleIndex,
                )
            }
    }

    private fun msToSamples(ms: Int, sampleRateHz: Int): Long =
        (ms.toLong() * sampleRateHz.toLong()) / 1_000L

    private fun samplesToMs(samples: Long, sampleRateHz: Int): Double =
        samples.toDouble() * 1_000.0 / sampleRateHz.toDouble()

    private data class RawWakeDetection(
        val keyword: String,
        val detectionSampleIndex: Long,
        val score: Float?,
    )
}
