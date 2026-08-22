package com.soul.aihub.voice

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.SystemClock
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Canonical Okja microphone owner.
 *
 * Production rule: no wake-word, VAD, ASR, or diagnostic consumer may create a
 * second AudioRecord. They consume [frames] and request pre-roll snapshots.
 *
 * A process-wide lease prevents two AudioEngine instances from owning AudioRecord
 * concurrently. The ring is cleared at every capture start so pre-roll can never
 * contain PCM from a previous microphone epoch.
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

        private const val STOP_JOIN_TIMEOUT_MS = 1_500L
        private val processMicOwner = AtomicReference<AudioEngine?>(null)
    }

    private val running = AtomicBoolean(false)
    private val closed = AtomicBoolean(false)
    private val lifecycleLock = Any()
    private val ring = PcmRingBuffer(SAMPLE_RATE_HZ, ringCapacityMs)
    private var captureThread: Thread? = null
    private var record: AudioRecord? = null

    private val mutableFrames = MutableSharedFlow<PcmFrame>(
        replay = 0,
        extraBufferCapacity = 16,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    override val frames: SharedFlow<PcmFrame> = mutableFrames.asSharedFlow()

    override fun readPreRollWindow(durationMs: Int): PcmWindow {
        require(durationMs in 0..ringCapacityMs) {
            "pre-roll must be within 0..$ringCapacityMs ms"
        }
        return ring.snapshotLatestWindow(durationMs)
    }

    /**
     * Starts the process's single microphone capture loop. RECORD_AUDIO permission must have
     * already been granted by the caller. A true return means AudioRecord was initialized and
     * entered RECORDSTATE_RECORDING before the capture thread was launched.
     */
    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        synchronized(lifecycleLock) {
            if (closed.get() || running.get() || record != null || captureThread != null) {
                return false
            }
            if (!processMicOwner.compareAndSet(null, this)) {
                return false
            }

            val localRecord = try {
                createStartedAudioRecord()
            } catch (_: Throwable) {
                processMicOwner.compareAndSet(this, null)
                return false
            }

            // A new capture epoch starts at sample index 0. Never expose stale pre-roll.
            ring.clear()
            record = localRecord
            running.set(true)

            val thread = Thread(
                { captureLoop(localRecord) },
                "Okja-AudioEngine",
            )
            captureThread = thread
            return try {
                thread.start()
                true
            } catch (_: Throwable) {
                running.set(false)
                captureThread = null
                record = null
                safeStop(localRecord)
                safeRelease(localRecord)
                processMicOwner.compareAndSet(this, null)
                false
            }
        }
    }

    fun isRunning(): Boolean = running.get()

    /**
     * Stops capture and waits briefly for the read loop to release AudioRecord. If a platform bug
     * prevents timely shutdown, the process-wide lease remains held, so a second owner still cannot
     * start and violate the microphone invariant.
     */
    fun stop() {
        val localRecord: AudioRecord?
        val localThread: Thread?
        synchronized(lifecycleLock) {
            if (!running.get() && record == null && captureThread == null) return
            running.set(false)
            localRecord = record
            localThread = captureThread
        }

        localRecord?.let(::safeStop)
        if (localThread != null && localThread !== Thread.currentThread()) {
            try {
                localThread.join(STOP_JOIN_TIMEOUT_MS)
            } catch (_: InterruptedException) {
                Thread.currentThread().interrupt()
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun createStartedAudioRecord(): AudioRecord {
        val minBytes = AudioRecord.getMinBufferSize(
            SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        check(minBytes > 0) { "AudioRecord buffer unavailable: $minBytes" }

        val localRecord = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE_HZ,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBytes, FRAME_SAMPLES * 2 * 8),
        )
        if (localRecord.state != AudioRecord.STATE_INITIALIZED) {
            safeRelease(localRecord)
            error("AudioRecord failed to initialize")
        }

        try {
            localRecord.startRecording()
            check(localRecord.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                "AudioRecord failed to enter recording state"
            }
            return localRecord
        } catch (t: Throwable) {
            safeStop(localRecord)
            safeRelease(localRecord)
            throw t
        }
    }

    private fun captureLoop(localRecord: AudioRecord) {
        val frame = ShortArray(FRAME_SAMPLES)
        var nextSequence = 0L
        var nextSampleIndex = 0L
        try {
            while (running.get()) {
                val n = try {
                    localRecord.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING)
                } catch (_: Throwable) {
                    break
                }
                if (n == 0) continue
                if (n < 0) break

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
            running.set(false)
            safeStop(localRecord)
            safeRelease(localRecord)
            synchronized(lifecycleLock) {
                if (record === localRecord) record = null
                if (captureThread === Thread.currentThread()) captureThread = null
            }
            processMicOwner.compareAndSet(this, null)
        }
    }

    private fun safeStop(audioRecord: AudioRecord) {
        try {
            if (audioRecord.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                audioRecord.stop()
            }
        } catch (_: Throwable) {
            // Shutdown remains fail-closed: the process lease is not released until captureLoop exits.
        }
    }

    private fun safeRelease(audioRecord: AudioRecord) {
        try {
            audioRecord.release()
        } catch (_: Throwable) {
            // Resource release is best-effort; process lease ordering still prevents a second owner.
        }
    }

    override fun close() {
        if (!closed.compareAndSet(false, true)) return
        stop()
    }
}
