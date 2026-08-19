package com.soul.aihub.voice

/** Canonical Okja microphone frame: 16 kHz, mono, signed PCM16. */
data class PcmFrame(
    val samples: ShortArray,
    val capturedAtElapsedRealtimeNs: Long,
)
