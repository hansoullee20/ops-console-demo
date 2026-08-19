package com.soul.aihub.voice

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Canonical Okja microphone owner.
 *
 * Production rule: no wake-word, VAD, ASR, or diagnostic consumer may create a
 * second AudioRecord. They consume [frames] and request pre-roll snapshots.
 */
class AudioEngine(
    private val ringCapacityMs: Int = DEFAULT_RING_CAPACITY_MS,
) : PcmAudioSource, AutoCloseable {

    companion object {
        const val SAMPLE_RATE_HZ = 16_000
        const val FRAME_MS = 20
        const val FRAME_SAMPLES = SAMPLE_RATE_HZ * FRAME_MS / 1000
        const val DEFAULT_RING_CAPACITY_MS = 3_000
        const val DEFAULT_PRE_ROLL_MS = 1_500
    }

    private val running = AtomicBoolean(false)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var captureJob: Job? = null
    private val ring = PcmRingBuffer(SAMPLE_RATE_HZ, ringCapacityMs)
    private val recordLock = Any()
    private var record: AudioRecord? = null

    private val mutableFrames = MutableSharedFlow<PcmFrame>(
        replay = 0,
        extraBufferCapacity = 16,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    override val frames: SharedFlow<PcmFrame> = mutableFrames.asSharedFlow()

    override fun readPreRoll(durationMs: Int): ShortArray {
        require(durationMs in 0..ringCapacityMs) {
            "pre-roll must be within 0..$ringCapacityMs ms"
        }
        return ring.snapshotLatest(durationMs)
    }

    /**
     * Starts the single microphone capture loop. RECORD_AUDIO permission must have
     * already been granted by the caller.
     */
    fun start(): Boolean {
        if (!running.compareAndSet(false, true)) return false
        captureJob = scope.launch { captureLoop() }
        return true
    }

    fun isRunning(): Boolean = running.get()

    fun stop() {
        if (!running.getAndSet(false)) return
        synchronized(recordLock) {
            try {
                record?.stop()
            } catch (_: Exception) {
            }
        }
        captureJob?.cancel()
        captureJob = null
        releaseRecord()
    }

    @SuppressLint("MissingPermission")
    private fun captureLoop() {
        val minBytes = AudioRecord.getMinBufferSize(
            SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        require(minBytes > 0) { "AudioRecord buffer unavailable: $minBytes" }

        val localRecord = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBytes, FRAME_SAMPLES * 2 * 8),
        )
        require(localRecord.state == AudioRecord.STATE_INITIALIZED) {
            localRecord.release()
            "AudioRecord failed to initialize"
        }

        synchronized(recordLock) {
            if (!running.get()) {
                localRecord.release()
                return
            }
            record = localRecord
        }

        val frame = ShortArray(FRAME_SAMPLES)
        var nextSequence = 0L
        var nextSampleIndex = 0L
        try {
            localRecord.startRecording()
            while (running.get()) {
                val n = localRecord.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING)
                if (n <= 0) continue
                val samples = if (n == frame.size) frame.copyOf() else frame.copyOf(n)
                ring.append(samples)
                mutableFrames.tryEmit(
                    PcmFrame(
                        samples = samples,
                        capturedAtElapsedRealtimeNs = SystemClock.elapsedRealtimeNanos(),
                        sequence = nextSequence,
                        startSampleIndex = nextSampleIndex,
                    ),
                )
                nextSequence += 1L
                nextSampleIndex += samples.size.toLong()
            }
        } finally {
            synchronized(recordLock) {
                if (record === localRecord) record = null
            }
            try {
                localRecord.stop()
            } catch (_: Exception) {
            }
            localRecord.release()
        }
    }

    private fun releaseRecord() {
        val local = synchronized(recordLock) {
            val current = record
            record = null
            current
        }
        if (local != null) {
            try {
                local.release()
            } catch (_: Exception) {
            }
        }
    }

    override fun close() {
        stop()
        scope.cancel()
    }
}
