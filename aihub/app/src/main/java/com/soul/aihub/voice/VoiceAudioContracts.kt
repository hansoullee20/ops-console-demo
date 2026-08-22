package com.soul.aihub.voice

/** Wake engines are pure PCM consumers. They never acquire the microphone. */
interface WakeDetector : AutoCloseable {
    fun accept(frame: PcmFrame): WakeDetection?
    override fun close() = Unit
}

data class WakeDetection(
    val keyword: String,
    val detectedAtElapsedRealtimeNs: Long,
    val score: Float? = null,
)

/** Streaming ASR engines consume pre-roll and subsequent live PCM from AudioEngine. */
interface StreamingAsrEngine : AutoCloseable {
    fun begin(preRollPcm16: ShortArray)
    fun accept(frame: PcmFrame): AsrUpdate?
    fun finish(): AsrUpdate?
    fun reset()
    override fun close() = Unit
}

data class AsrUpdate(
    val text: String,
    val isFinal: Boolean,
    val producedAtElapsedRealtimeNs: Long,
)
