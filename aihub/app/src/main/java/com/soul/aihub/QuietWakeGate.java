package com.soul.aihub;

import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Handler;
import android.os.Looper;

/**
 * Interim quiet gate for the SpeechRecognizer fallback wake path.
 * It does NOT recognize the wake word. It only waits locally for sustained
 * microphone energy before allowing one short SpeechRecognizer wake session.
 * The validated dedicated wake-word model will replace this gate later.
 */
final class QuietWakeGate {
    interface Callback { void onSpeechActivity(); void onFailure(String reason); }

    private static final int SAMPLE_RATE = 16000;
    private static final int FRAME_SAMPLES = 640; // 40 ms
    private static final double RMS_THRESHOLD = 900.0;
    private static final int REQUIRED_HOT_FRAMES = 3;

    private final Callback callback;
    private final Handler main = new Handler(Looper.getMainLooper());
    private volatile boolean running;
    private Thread worker;
    private AudioRecord record;

    QuietWakeGate(Callback callback) { this.callback = callback; }

    synchronized boolean isRunning() { return running; }

    synchronized void start() {
        if (running) return;
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
                    Math.max(min, FRAME_SAMPLES * 4));
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
        int hot = 0;
        try {
            record.startRecording();
            while (running) {
                int n = record.read(frame, 0, frame.length, AudioRecord.READ_BLOCKING);
                if (n <= 0) continue;
                double sum = 0.0;
                for (int i = 0; i < n; i++) {
                    double s = frame[i];
                    sum += s * s;
                }
                double rms = Math.sqrt(sum / n);
                hot = rms >= RMS_THRESHOLD ? hot + 1 : Math.max(0, hot - 1);
                if (hot >= REQUIRED_HOT_FRAMES) {
                    running = false;
                    break;
                }
            }
        } catch (RuntimeException e) {
            if (running) main.post(() -> callback.onFailure("audio_read_failure"));
            running = false;
        } finally {
            releaseRecord();
        }
        if (hot >= REQUIRED_HOT_FRAMES) main.post(callback::onSpeechActivity);
    }

    synchronized void stop() {
        running = false;
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
