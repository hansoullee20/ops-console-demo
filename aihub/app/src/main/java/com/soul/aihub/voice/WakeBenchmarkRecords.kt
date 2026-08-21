package com.soul.aihub.voice

/**
 * Stable JSONL records for reproducible wake benchmarks.
 *
 * Keep these records intentionally dependency-free so JVM tests and Android debug
 * tooling can emit identical lines without pulling a JSON runtime into the audio core.
 * Raw household audio is not embedded here; records reference a case/clip id only.
 */
data class IntentionalWakeAnnotation(
    val caseId: String,
    val attemptId: String,
    val keyword: String,
    val keywordEndSampleIndex: Long,
    val speakerId: String? = null,
    val condition: String? = null,
    val matchEarlyMs: Int = 200,
    val matchLateMs: Int = 1_000,
) {
    init {
        require(caseId.isNotBlank()) { "caseId must not be blank" }
        require(attemptId.isNotBlank()) { "attemptId must not be blank" }
        require(keyword.isNotBlank()) { "keyword must not be blank" }
        require(keywordEndSampleIndex >= 0L) { "keywordEndSampleIndex must be non-negative" }
        require(matchEarlyMs >= 0) { "matchEarlyMs must be non-negative" }
        require(matchLateMs >= 0) { "matchLateMs must be non-negative" }
    }

    fun toJsonLine(): String = jsonObject(
        "schema_version" to "1.0",
        "record_type" to "intentional_wake",
        "case_id" to caseId,
        "attempt_id" to attemptId,
        "keyword" to keyword,
        "keyword_end_sample_index" to keywordEndSampleIndex,
        "speaker_id" to speakerId,
        "condition" to condition,
        "match_early_ms" to matchEarlyMs,
        "match_late_ms" to matchLateMs,
    )
}

data class WakeCandidateRecord(
    val caseId: String,
    val candidateId: String,
    val detectorName: String,
    val keyword: String,
    val detectionSampleIndex: Long,
    val score: Double?,
    val decision: String,
    val matchedAttemptId: String? = null,
    val reviewClass: String? = null,
    val clipId: String? = null,
) {
    init {
        require(caseId.isNotBlank()) { "caseId must not be blank" }
        require(candidateId.isNotBlank()) { "candidateId must not be blank" }
        require(detectorName.isNotBlank()) { "detectorName must not be blank" }
        require(keyword.isNotBlank()) { "keyword must not be blank" }
        require(detectionSampleIndex >= 0L) { "detectionSampleIndex must be non-negative" }
        require(score == null || score.isFinite()) { "score must be finite" }
        require(decision.isNotBlank()) { "decision must not be blank" }
    }

    fun toJsonLine(): String = jsonObject(
        "schema_version" to "1.0",
        "record_type" to "wake_candidate",
        "case_id" to caseId,
        "candidate_id" to candidateId,
        "detector_name" to detectorName,
        "keyword" to keyword,
        "detection_sample_index" to detectionSampleIndex,
        "score" to score,
        "decision" to decision,
        "matched_attempt_id" to matchedAttemptId,
        "review_class" to reviewClass,
        "clip_id" to clipId,
    )
}

/**
 * One positive attempt reduced to its strongest detector score.
 *
 * Threshold sweeping uses one row per intentional attempt so multiple frame-level
 * candidates cannot accidentally count as multiple successful wake attempts.
 */
data class WakePositiveAttemptScore(
    val attemptId: String,
    val maxScore: Double,
    val latencyMs: Double? = null,
) {
    init {
        require(attemptId.isNotBlank()) { "attemptId must not be blank" }
        require(maxScore.isFinite()) { "maxScore must be finite" }
        require(latencyMs == null || latencyMs.isFinite()) { "latencyMs must be finite" }
    }
}

data class WakeNegativeCandidateScore(
    val candidateId: String,
    val score: Double,
) {
    init {
        require(candidateId.isNotBlank()) { "candidateId must not be blank" }
        require(score.isFinite()) { "score must be finite" }
    }
}

data class WakeThresholdDataset(
    val positiveAttempts: List<WakePositiveAttemptScore>,
    val negativeCandidates: List<WakeNegativeCandidateScore>,
    val negativeListeningHours: Double,
) {
    init {
        require(negativeListeningHours >= 0.0 && negativeListeningHours.isFinite()) {
            "negativeListeningHours must be finite and non-negative"
        }
        require(positiveAttempts.map { it.attemptId }.distinct().size == positiveAttempts.size) {
            "positive attempt ids must be unique"
        }
        require(negativeCandidates.map { it.candidateId }.distinct().size == negativeCandidates.size) {
            "negative candidate ids must be unique"
        }
    }
}

data class WakeThresholdResult(
    val threshold: Double,
    val intentionalAttempts: Int,
    val detectedAttempts: Int,
    val misses: Int,
    val recall: Double?,
    val falseRejectRate: Double?,
    val falseActivations: Int,
    val negativeListeningHours: Double,
    val falseActivationsPerHour: Double?,
    val zeroEventUpperBound95PerHour: Double?,
    val latencyP50Ms: Double?,
    val latencyP95Ms: Double?,
)

/** Deterministic threshold sweep over already-recorded detector scores. */
class WakeThresholdSweep {
    fun run(dataset: WakeThresholdDataset, thresholds: List<Double>): List<WakeThresholdResult> {
        require(thresholds.all { it.isFinite() }) { "thresholds must be finite" }

        return thresholds
            .distinct()
            .sorted()
            .map { threshold -> score(dataset, threshold) }
    }

    private fun score(dataset: WakeThresholdDataset, threshold: Double): WakeThresholdResult {
        val passingAttempts = dataset.positiveAttempts.filter { it.maxScore >= threshold }
        val attempts = dataset.positiveAttempts.size
        val detected = passingAttempts.size
        val misses = attempts - detected
        val recall = if (attempts == 0) null else detected.toDouble() / attempts.toDouble()
        val falseRejectRate = recall?.let { 1.0 - it }
        val falseActivations = dataset.negativeCandidates.count { it.score >= threshold }
        val hours = dataset.negativeListeningHours
        val falseActivationsPerHour = if (hours <= 0.0) {
            null
        } else {
            falseActivations.toDouble() / hours
        }
        val zeroEventUpperBound95PerHour = if (hours > 0.0 && falseActivations == 0) {
            -kotlin.math.ln(0.05) / hours
        } else {
            null
        }
        val latencies = passingAttempts.mapNotNull { it.latencyMs }.sorted()

        return WakeThresholdResult(
            threshold = threshold,
            intentionalAttempts = attempts,
            detectedAttempts = detected,
            misses = misses,
            recall = recall,
            falseRejectRate = falseRejectRate,
            falseActivations = falseActivations,
            negativeListeningHours = hours,
            falseActivationsPerHour = falseActivationsPerHour,
            zeroEventUpperBound95PerHour = zeroEventUpperBound95PerHour,
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

private fun jsonObject(vararg fields: Pair<String, Any?>): String = buildString {
    append('{')
    fields.forEachIndexed { index, (key, value) ->
        if (index > 0) append(',')
        append('"').append(jsonEscape(key)).append('"').append(':')
        appendJsonValue(value)
    }
    append('}')
}

private fun StringBuilder.appendJsonValue(value: Any?) {
    when (value) {
        null -> append("null")
        is String -> append('"').append(jsonEscape(value)).append('"')
        is Int, is Long -> append(value.toString())
        is Double -> {
            require(value.isFinite()) { "JSON numbers must be finite" }
            append(value.toString())
        }
        is Float -> {
            require(value.isFinite()) { "JSON numbers must be finite" }
            append(value.toString())
        }
        is Boolean -> append(if (value) "true" else "false")
        else -> error("unsupported JSON value type: ${value::class.java.name}")
    }
}

private fun jsonEscape(value: String): String = buildString(value.length) {
    value.forEach { ch ->
        when (ch) {
            '"' -> append("\\\"")
            '\\' -> append("\\\\")
            '\b' -> append("\\b")
            '\u000C' -> append("\\f")
            '\n' -> append("\\n")
            '\r' -> append("\\r")
            '\t' -> append("\\t")
            else -> {
                if (ch.code < 0x20) {
                    append("\\u")
                    append(ch.code.toString(16).padStart(4, '0'))
                } else {
                    append(ch)
                }
            }
        }
    }
}
