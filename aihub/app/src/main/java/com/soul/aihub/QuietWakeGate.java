package com.soul.aihub;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;

/**
 * Interim quiet onset gate for the SpeechRecognizer fallback wake path.
 *
 * This class does NOT recognize the wake word. It only waits locally for a
 * speech-like energy onset before handing the microphone to SpeechRecognizer.
 * The threshold adapts to the room noise floor so a fixed RMS value does not
 * become either deaf in a quiet room or permanently hot in a noisy one.
 *
 * A refractory period is enforced after every detected onset. This prevents
 * SpeechRecognizer/system audio emitted during the handoff from immediately
 * re-opening the gate and creating a beep/retrigger loop.
 */
final class QuietWakeGate {
    interface Callback { void onSpeechActivity(); void onFailure(String reason); }

    private static final int SAMPLE_RATE = 16000;
    private static final int FRAME_SAMPLES = 320; // 20 ms: minimize wake-word clipping.
    private static final double INITIAL_NOISE_FLOOR = 180.0;
    private static final double MIN_TRIGGER_RMS = 480.0;
    private static final double NOISE_MULTIPLIER = 3.0;
    private static final double NOISE_ALPHA = 0.025;
    private static final long RETRIGGER_GUARD_MS = 2600L;

    private final Callback callback;
    private final Handler main = new Handler(Looper.getMainLooper());
    private volatile boolean running;
    private Thread worker;
    private AudioRecord record;
    private long nextEligibleStartMs = 0L;

    private final Runnable delayedStart = new Runnable() {
        @Override public void run() { start(); }
    };

    QuietWakeGate(Callback callback) { this.callback = callback; }

    synchronized boolean isRunning() { return running; }

    synchronized void start() {
        if (running) return;
        main.removeCallbacks(delayedStart);
        long remaining = nextEligibleStartMs - SystemClock.elapsedRealtime();
        if (remaining > 0L) {
            main.postDelayed(delayedStart, remaining);
            return;
        }
        int min = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (min <= 0) {
            main.post(() -> callback.onFailure("audio_buffer_unavailable"));
            return;
        }
        try {
            record = new AudioRecord(
                    MediaRecorder.AudioSource.VOICE_RECOGNITION,
                    SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    Math.max(min, FRAME_SAMPLES * 8));
            if (record.getState() != AudioRecord.STATE_INITIALIZED) {
                releaseRecord();
                main.post(() -> callback.onFailure("audio_record_uninitialized"));
                return;
            }
            running = true;
            worker = new Thread(this::loop, "okja-quiet-wake-gate");
            worker.setDaemon(true);
            worker.start();
        } catch (SecurityException e) {
            releaseRecord();
            main.post(() -> callback.onFailure("audio_permission"));
        } catch (RuntimeException e) {
            releaseRecord();
            main.post(() -> callback.onFailure("audio_start_failure"));
        }
    }

    private void loop() {
        short[] frame = new short[FRAME_SAMPLES];
        double noiseFloor = INITIAL_NOISE_FLOOR;
        boolean onset = false;
        try {
            record.startRecording();
            while (running) {
                int n = record.read(frame, 0, frame.length, AudioRecord.READ_BLOCKING);
                if (n <= 0) continue;
                double sum = 0.0;
                for (int i = 0; i < n; i++) {
                    double sample = frame[i];
                    sum += sample * sample;
                }
                double rms = Math.sqrt(sum / n);
                double trigger = Math.max(MIN_TRIGGER_RMS, noiseFloor * NOISE_MULTIPLIER);
                if (rms >= trigger) {
                    onset = true;
                    nextEligibleStartMs = SystemClock.elapsedRealtime() + RETRIGGER_GUARD_MS;
                    running = false;
                    break;
                }
                // Learn only sub-trigger room energy. Speech/transients must not raise
                // the baseline and make the next wake progressively harder.
                noiseFloor = noiseFloor * (1.0 - NOISE_ALPHA) + rms * NOISE_ALPHA;
            }
        } catch (RuntimeException e) {
            if (running) main.post(() -> callback.onFailure("audio_read_failure"));
            running = false;
        } finally {
            releaseRecord();
        }
        if (onset) main.post(callback::onSpeechActivity);
    }

    synchronized void stop() {
        running = false;
        main.removeCallbacks(delayedStart);
        if (record != null) {
            try { record.stop(); } catch (Exception ignored) {}
        }
        releaseRecord();
    }

    private synchronized void releaseRecord() {
        if (record != null) {
            try { record.release(); } catch (Exception ignored) {}
            record = null;
        }
    }
}
