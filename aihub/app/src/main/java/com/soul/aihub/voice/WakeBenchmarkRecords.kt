package com.soul.aihub.voice

/**
 * Android-side JSONL records aligned with `aihub/wakeword/v4_benchmark_schema.json`.
 *
 * Keep these dependency-free so JVM tests and Android diagnostic tooling emit the
 * same benchmark contract. Additional sample-index fields are allowed by the v4
 * schema and let the PCM replay harness preserve exact sample-time provenance.
 */
data class IntentionalWakeAnnotation(
    val eventId: String,
    val recordingId: String,
    val timestampMs: Double,
    val phrase: String,
    val language: String,
    val speakerId: String,
    val condition: String,
    val roomId: String,
    val background: String,
    val mentionContext: Boolean,
    val keywordEndSampleIndex: Long? = null,
    val distanceM: Double? = null,
    val direction: String? = null,
    val voiceLevel: String? = null,
    val selfTts: Boolean? = null,
    val timeBucket: String? = null,
) {
    init {
        require(eventId.isNotBlank()) { "eventId must not be blank" }
        require(recordingId.isNotBlank()) { "recordingId must not be blank" }
        require(timestampMs >= 0.0 && timestampMs.isFinite()) { "timestampMs must be finite and non-negative" }
        require(phrase.isNotBlank()) { "phrase must not be blank" }
        require(language.length >= 2) { "language must contain at least two characters" }
        require(speakerId.isNotBlank()) { "speakerId must not be blank" }
        require(condition.isNotBlank()) { "condition must not be blank" }
        require(roomId.isNotBlank()) { "roomId must not be blank" }
        require(background.isNotBlank()) { "background must not be blank" }
        require(keywordEndSampleIndex == null || keywordEndSampleIndex >= 0L) {
            "keywordEndSampleIndex must be non-negative"
        }
        require(distanceM == null || (distanceM >= 0.0 && distanceM.isFinite())) {
            "distanceM must be finite and non-negative"
        }
        require(timeBucket == null || timeBucket == "day" || timeBucket == "night") {
            "timeBucket must be day, night, or null"
        }
    }

    fun toJsonLine(): String {
        val fields = mutableListOf<Pair<String, Any?>>(
            "schema_version" to 1,
            "event_id" to eventId,
            "recording_id" to recordingId,
            "timestamp_ms" to timestampMs,
            "intentional_invocation" to true,
            "phrase" to phrase,
            "language" to language,
            "speaker_id" to speakerId,
            "condition" to condition,
            "room_id" to roomId,
            "background" to background,
            "mention_context" to mentionContext,
        )
        distanceM?.let { fields += "distance_m" to it }
        direction?.let { fields += "direction" to it }
        voiceLevel?.let { fields += "voice_level" to it }
        selfTts?.let { fields += "self_tts" to it }
        timeBucket?.let { fields += "time_bucket" to it }
        keywordEndSampleIndex?.let { fields += "keyword_end_sample_index" to it }
        return jsonObject(*fields.toTypedArray())
    }
}

data class WakeCandidateRecord(
    val detectionId: String,
    val recordingId: String,
    val timestampMs: Double,
    val modelName: String,
    val modelVersion: String,
    val modelSha: String,
    val threshold: Double,
    val score: Double,
    val deviceId: String,
    val roomId: String? = null,
    val latencyMs: Double? = null,
    val accepted: Boolean,
    val detectionSampleIndex: Long? = null,
    val matchedAttemptId: String? = null,
    val reviewClass: String? = null,
    val clipId: String? = null,
) {
    init {
        require(detectionId.isNotBlank()) { "detectionId must not be blank" }
        require(recordingId.isNotBlank()) { "recordingId must not be blank" }
        require(timestampMs >= 0.0 && timestampMs.isFinite()) { "timestampMs must be finite and non-negative" }
        require(modelName.isNotBlank()) { "modelName must not be blank" }
        require(modelVersion.isNotBlank()) { "modelVersion must not be blank" }
        require(MODEL_SHA.matches(modelSha)) { "modelSha must be 7-64 lowercase hex characters" }
        require(threshold.isFinite()) { "threshold must be finite" }
        require(score.isFinite()) { "score must be finite" }
        require(deviceId.isNotBlank()) { "deviceId must not be blank" }
        require(latencyMs == null || latencyMs.isFinite()) { "latencyMs must be finite" }
        require(detectionSampleIndex == null || detectionSampleIndex >= 0L) {
            "detectionSampleIndex must be non-negative"
        }
    }

    fun toJsonLine(): String {
        val fields = mutableListOf<Pair<String, Any?>>(
            "schema_version" to 1,
            "detection_id" to detectionId,
            "recording_id" to recordingId,
            "timestamp_ms" to timestampMs,
            "model_name" to modelName,
            "model_version" to modelVersion,
            // Compatibility aliases for the current v4_eval.py loader. The canonical
            // schema fields above remain authoritative; additional properties are allowed.
            "model" to modelName,
            "version" to modelVersion,
            "model_sha" to modelSha,
            "threshold" to threshold,
            "score" to score,
            "device_id" to deviceId,
            "accepted" to accepted,
        )
        roomId?.let { fields += "room_id" to it }
        latencyMs?.let { fields += "latency_ms" to it }
        detectionSampleIndex?.let { fields += "detection_sample_index" to it }
        matchedAttemptId?.let { fields += "matched_attempt_id" to it }
        reviewClass?.let { fields += "review_class" to it }
        clipId?.let { fields += "clip_id" to it }
        return jsonObject(*fields.toTypedArray())
    }

    companion object {
        private val MODEL_SHA = Regex("^[0-9a-f]{7,64}$")
    }
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
