package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WakeBenchmarkRecordsTest {
    @Test
    fun intentionalWakeJsonLineMatchesExistingV4ContractAndEscapesText() {
        val line = IntentionalWakeAnnotation(
            eventId = "attempt-1",
            recordingId = "case-1",
            timestampMs = 771.5,
            phrase = "옥자야",
            language = "ko-KR",
            speakerId = "speaker\"A",
            condition = "intentional",
            roomId = "livingroom",
            background = "tv\non",
            mentionContext = false,
            keywordEndSampleIndex = 12_345L,
            distanceM = 2.5,
            direction = "front",
            voiceLevel = "normal",
            selfTts = false,
            timeBucket = "day",
        ).toJsonLine()

        assertEquals(
            "{\"schema_version\":1,\"event_id\":\"attempt-1\",\"recording_id\":\"case-1\",\"timestamp_ms\":771.5,\"intentional_invocation\":true,\"phrase\":\"옥자야\",\"language\":\"ko-KR\",\"speaker_id\":\"speaker\\\"A\",\"condition\":\"intentional\",\"room_id\":\"livingroom\",\"background\":\"tv\\non\",\"distance_m\":2.5,\"direction\":\"front\",\"voice_level\":\"normal\",\"mention_context\":false,\"self_tts\":false,\"time_bucket\":\"day\",\"keyword_end_sample_index\":12345}",
            line,
        )
    }

    @Test
    fun candidateJsonLineMatchesExistingDetectionContractAndPreservesReviewNulls() {
        val line = WakeCandidateRecord(
            detectionId = "candidate-7",
            recordingId = "negative-1",
            timestampMs = 200.0,
            modelName = "stage-a",
            modelVersion = "0.1-test",
            modelSha = "abcdef1",
            threshold = 0.5,
            score = 0.61,
            deviceId = "fold4-01",
            roomId = "livingroom",
            accepted = false,
            detectionSampleIndex = 3_200L,
        ).toJsonLine()

        assertTrue(line.contains("\"schema_version\":1"))
        assertTrue(line.contains("\"score\":0.61"))
        assertTrue(line.contains("\"accepted\":false"))
        assertTrue(line.contains("\"matched_attempt_id\":null"))
        assertTrue(line.contains("\"review_class\":null"))
        assertTrue(line.contains("\"clip_id\":null"))
    }

    @Test
    fun thresholdSweepRewardsAbstentionWithoutHidingFalseActivations() {
        val dataset = WakeThresholdDataset(
            positiveAttempts = listOf(
                WakePositiveAttemptScore("a", maxScore = 0.95, latencyMs = 100.0),
                WakePositiveAttemptScore("b", maxScore = 0.70, latencyMs = 200.0),
                WakePositiveAttemptScore("c", maxScore = 0.40, latencyMs = 300.0),
            ),
            negativeCandidates = listOf(
                WakeNegativeCandidateScore("n1", 0.80),
                WakeNegativeCandidateScore("n2", 0.30),
            ),
            negativeListeningHours = 10.0,
        )

        val results = WakeThresholdSweep().run(dataset, listOf(0.9, 0.5, 0.5))

        assertEquals(listOf(0.5, 0.9), results.map { it.threshold })

        val permissive = results[0]
        assertEquals(2, permissive.detectedAttempts)
        assertEquals(1, permissive.misses)
        assertEquals(2.0 / 3.0, permissive.recall!!, 1e-9)
        assertEquals(1, permissive.falseActivations)
        assertEquals(0.1, permissive.falseActivationsPerHour!!, 1e-9)
        assertNull(permissive.zeroEventUpperBound95PerHour)
        assertEquals(150.0, permissive.latencyP50Ms!!, 1e-9)
        assertEquals(195.0, permissive.latencyP95Ms!!, 1e-9)

        val strict = results[1]
        assertEquals(1, strict.detectedAttempts)
        assertEquals(2, strict.misses)
        assertEquals(1.0 / 3.0, strict.recall!!, 1e-9)
        assertEquals(0, strict.falseActivations)
        assertEquals(0.0, strict.falseActivationsPerHour!!, 0.0)
        assertEquals(-kotlin.math.ln(0.05) / 10.0, strict.zeroEventUpperBound95PerHour!!, 1e-12)
        assertEquals(100.0, strict.latencyP50Ms!!, 0.0)
        assertEquals(100.0, strict.latencyP95Ms!!, 0.0)
    }

    @Test(expected = IllegalArgumentException::class)
    fun duplicateAttemptIdsAreRejected() {
        WakeThresholdDataset(
            positiveAttempts = listOf(
                WakePositiveAttemptScore("same", 0.9),
                WakePositiveAttemptScore("same", 0.8),
            ),
            negativeCandidates = emptyList(),
            negativeListeningHours = 0.0,
        )
    }
}
