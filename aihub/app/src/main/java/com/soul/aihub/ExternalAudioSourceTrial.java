package com.soul.aihub;

import android.app.Activity;
import android.content.Intent;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;

import org.json.JSONObject;

import java.io.OutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;

/**
 * Diagnostic-only trial for Android API 33+ RecognizerIntent.EXTRA_AUDIO_SOURCE.
 *
 * The test keeps one AudioRecord alive, maintains a two-second PCM ring buffer,
 * detects a speech-like onset locally, then feeds pre-roll + live PCM through a
 * ParcelFileDescriptor pipe into SpeechRecognizer. It never releases/reacquires
 * the microphone at wake onset. If the recognition service ignores
 * EXTRA_AUDIO_SOURCE and opens its own microphone, DiagnosticTrace's recording
 * callback should expose the extra capture session.
 */
final class ExternalAudioSourceTrial {
    interface Callback {
        void onState(String state);
        void onResult(String text);
    }

    private static final int SAMPLE_RATE = 16000;
    private static final int FRAME_SAMPLES = 320; // 20 ms
    private static final int PRE_ROLL_SAMPLES = SAMPLE_RATE * 2;
    private static final double INITIAL_NOISE_FLOOR = 180.0;
    private static final double MIN_TRIGGER_RMS = 480.0;
    private static final double NOISE_MULTIPLIER = 3.0;
    private static final double NOISE_ALPHA = 0.025;
    private static final int END_SILENCE_FRAMES = 45; // ~900 ms
    private static final long MAX_CAPTURE_AFTER_ONSET_MS = 7000L;
    private static final short[] END = new short[0];

    private final Activity activity;
    private final Callback callback;
    private final BlockingQueue<short[]> pcmQueue = new ArrayBlockingQueue<>(400);

    private volatile boolean running;
    private volatile boolean triggered;
    private Thread captureThread;
    private Thread writerThread;
    private AudioRecord audioRecord;
    private SpeechRecognizer recognizer;
    private ParcelFileDescriptor readPfd;
    private ParcelFileDescriptor writePfd;
    private OutputStream pipeOutput;

    ExternalAudioSourceTrial(Activity activity, Callback callback) {
        this.activity = activity;
        this.callback = callback;
    }

    void start() {
        stop();
        if (Build.VERSION.SDK_INT < 33) {
            callback.onState("F_UNSUPPORTED_API");
            callback.onResult("Mode F requires Android API 33+");
            return;
        }
        running = true;
        triggered = false;
        pcmQueue.clear();
        callback.onState("F_AUDIO_WAIT");
        DiagnosticTrace.log("F_TRIAL_START", null);
        captureThread = new Thread(this::captureLoop, "okja-f-audio-capture");
        captureThread.setDaemon(true);
        captureThread.start();
    }

    void stop() {
        running = false;
        AudioRecord r = audioRecord;
        if (r != null) {
            try { r.stop(); } catch (Exception ignored) {}
        }
        pcmQueue.offer(END);
        closePipeOutput();
        destroyRecognizer();
        closeReadPfd();
    }

    private void captureLoop() {
        int min = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT);
        if (min <= 0) {
            fail("F_AUDIO_BUFFER_UNAVAILABLE");
            return;
        }

        AudioRecord rec = null;
        try {
            rec = new AudioRecord(
                    MediaRecorder.AudioSource.VOICE_RECOGNITION,
                    SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    Math.max(min, FRAME_SAMPLES * 16));
            audioRecord = rec;
            if (rec.getState() != AudioRecord.STATE_INITIALIZED) {
                fail("F_AUDIO_UNINITIALIZED");
                return;
            }

            short[] frame = new short[FRAME_SAMPLES];
            PcmRing ring = new PcmRing(PRE_ROLL_SAMPLES);
            double noiseFloor = INITIAL_NOISE_FLOOR;
            int silenceFrames = 0;
            long onsetMs = 0L;

            rec.startRecording();
            DiagnosticTrace.log("F_AUDIO_RECORD_STARTED", null);

            while (running) {
                int n = rec.read(frame, 0, frame.length, AudioRecord.READ_BLOCKING);
                if (n <= 0) continue;

                double rms = rms(frame, n);
                double trigger = Math.max(MIN_TRIGGER_RMS, noiseFloor * NOISE_MULTIPLIER);
                ring.append(frame, n);

                if (!triggered && rms >= trigger) {
                    triggered = true;
                    onsetMs = SystemClock.elapsedRealtime();
                    JSONObject p = new JSONObject();
                    try {
                        p.put("rms", rms);
                        p.put("noise_floor", noiseFloor);
                        p.put("trigger", trigger);
                        p.put("pre_roll_capacity_samples", PRE_ROLL_SAMPLES);
                    } catch (Exception ignored) {}
                    DiagnosticTrace.log("F_ONSET", p);

                    short[] snapshot = ring.snapshot();
                    JSONObject q = new JSONObject();
                    try { q.put("samples", snapshot.length); } catch (Exception ignored) {}
                    DiagnosticTrace.log("F_PRE_ROLL_SNAPSHOT", q);

                    if (!preparePipeAndRecognizer()) return;
                    if (!offerPcm(snapshot)) return;
                    startWriter();
                    startRecognizerOnMain();
                    silenceFrames = 0;
                    continue; // onset frame is already included in snapshot
                }

                if (!triggered) {
                    noiseFloor = noiseFloor * (1.0 - NOISE_ALPHA) + rms * NOISE_ALPHA;
                    continue;
                }

                if (!offerPcm(Arrays.copyOf(frame, n))) return;

                if (rms > trigger * 0.72) silenceFrames = 0;
                else silenceFrames++;

                long afterOnset = SystemClock.elapsedRealtime() - onsetMs;
                if ((silenceFrames >= END_SILENCE_FRAMES && afterOnset >= 700L)
                        || afterOnset >= MAX_CAPTURE_AFTER_ONSET_MS) {
                    JSONObject p = new JSONObject();
                    try {
                        p.put("silence_frames", silenceFrames);
                        p.put("after_onset_ms", afterOnset);
                    } catch (Exception ignored) {}
                    DiagnosticTrace.log("F_AUDIO_INPUT_COMPLETE", p);
                    break;
                }
            }
        } catch (Exception e) {
            JSONObject p = new JSONObject();
            try {
                p.put("error", e.getClass().getSimpleName());
                p.put("message", String.valueOf(e.getMessage()));
            } catch (Exception ignored) {}
            DiagnosticTrace.log("F_AUDIO_EXCEPTION", p);
            fail("F_AUDIO_EXCEPTION");
        } finally {
            running = false;
            pcmQueue.offer(END);
            if (rec != null) {
                try { rec.stop(); } catch (Exception ignored) {}
                try { rec.release(); } catch (Exception ignored) {}
            }
            audioRecord = null;
            DiagnosticTrace.log("F_AUDIO_RECORD_RELEASED", null);
        }
    }

    private boolean preparePipeAndRecognizer() {
        try {
            ParcelFileDescriptor[] pipe = ParcelFileDescriptor.createPipe();
            readPfd = pipe[0];
            writePfd = pipe[1];
            pipeOutput = new ParcelFileDescriptor.AutoCloseOutputStream(writePfd);
            JSONObject p = new JSONObject();
            try { p.put("api", Build.VERSION.SDK_INT); } catch (Exception ignored) {}
            DiagnosticTrace.log("F_PIPE_CREATED", p);
            return true;
        } catch (Exception e) {
            JSONObject p = new JSONObject();
            try { p.put("error", e.getClass().getSimpleName()); } catch (Exception ignored) {}
            DiagnosticTrace.log("F_PIPE_ERROR", p);
            fail("F_PIPE_ERROR");
            return false;
        }
    }

    private void startWriter() {
        writerThread = new Thread(() -> {
            try {
                while (true) {
                    short[] pcm = pcmQueue.take();
                    if (pcm.length == 0) break;
                    byte[] bytes = pcm16le(pcm);
                    OutputStream out = pipeOutput;
                    if (out == null) break;
                    out.write(bytes);
                }
                OutputStream out = pipeOutput;
                if (out != null) out.flush();
            } catch (Exception e) {
                JSONObject p = new JSONObject();
                try { p.put("error", e.getClass().getSimpleName()); } catch (Exception ignored) {}
                DiagnosticTrace.log("F_PIPE_WRITE_ERROR", p);
            } finally {
                closePipeOutput();
                DiagnosticTrace.log("F_PIPE_EOF", null);
            }
        }, "okja-f-audio-pipe");
        writerThread.setDaemon(true);
        writerThread.start();
    }

    private boolean offerPcm(short[] pcm) {
        if (pcm == null || pcm.length == 0) return true;
        if (!pcmQueue.offer(pcm)) {
            DiagnosticTrace.log("F_PCM_QUEUE_OVERFLOW", null);
            fail("F_PCM_QUEUE_OVERFLOW");
            return false;
        }
        return true;
    }

    private void startRecognizerOnMain() {
        activity.runOnUiThread(() -> {
            if (!triggered) return;
            try {
                recognizer = SpeechRecognizer.createSpeechRecognizer(activity);
                recognizer.setRecognitionListener(listener());

                JSONObject impl = new JSONObject();
                try {
                    impl.put("external_audio_source", true);
                    impl.put("voice_recognition_service", android.provider.Settings.Secure.getString(
                            activity.getContentResolver(), "voice_recognition_service"));
                } catch (Exception ignored) {}
                DiagnosticTrace.log("SR_IMPLEMENTATION", impl);

                Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ko-KR");
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "ko-KR");
                i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
                i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5);
                i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, readPfd);
                i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, 1);
                i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, AudioFormat.ENCODING_PCM_16BIT);
                i.putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, SAMPLE_RATE);

                DiagnosticTrace.nextGeneration();
                DiagnosticTrace.log("F_SR_EXTERNAL_AUDIO_REQUESTED", null);
                DiagnosticTrace.log("SR_START_REQUESTED", null);
                callback.onState("F_SR_START_REQUESTED");
                recognizer.startListening(i);
                DiagnosticTrace.log("SR_START_RETURNED", null);
            } catch (Exception e) {
                JSONObject p = new JSONObject();
                try {
                    p.put("error", e.getClass().getSimpleName());
                    p.put("message", String.valueOf(e.getMessage()));
                } catch (Exception ignored) {}
                DiagnosticTrace.log("SR_START_EXCEPTION", p);
                fail("F_SR_START_EXCEPTION");
            }
        });
    }

    private RecognitionListener listener() {
        return new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle params) {
                DiagnosticTrace.log("SR_ON_READY", null);
                callback.onState("F_SR_ON_READY");
            }

            @Override public void onBeginningOfSpeech() {
                DiagnosticTrace.log("SR_BEGIN_SPEECH", null);
                callback.onState("F_SR_BEGIN_SPEECH");
            }

            @Override public void onRmsChanged(float rmsdB) {}
            @Override public void onBufferReceived(byte[] buffer) {}

            @Override public void onEndOfSpeech() {
                DiagnosticTrace.log("SR_END_SPEECH", null);
                callback.onState("F_SR_END_SPEECH");
            }

            @Override public void onError(int error) {
                JSONObject p = new JSONObject();
                try { p.put("error_code", error); } catch (Exception ignored) {}
                DiagnosticTrace.log("SR_ERROR", p);
                callback.onState("F_SR_ERROR_" + error);
                callback.onResult("SR error " + error + " · external-audio trial stopped");
                cleanupAfterRecognizer();
            }

            @Override public void onResults(Bundle results) {
                ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                DiagnosticTrace.logCandidates("SR_RESULTS", matches);
                boolean wake = containsWake(matches);
                JSONObject p = new JSONObject();
                try { p.put("wake_present", wake); } catch (Exception ignored) {}
                DiagnosticTrace.log(wake ? "WAKE_ACCEPT" : "WAKE_REJECT", p);
                callback.onState(wake ? "F_WAKE_ACCEPT" : "F_WAKE_REJECT");
                callback.onResult(matches == null ? "[]" : matches.toString());
                cleanupAfterRecognizer();
            }

            @Override public void onPartialResults(Bundle partialResults) {
                ArrayList<String> m = partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                DiagnosticTrace.logCandidates("SR_PARTIAL", m);
            }

            @Override public void onEvent(int eventType, Bundle params) {
                JSONObject p = new JSONObject();
                try { p.put("event_type", eventType); } catch (Exception ignored) {}
                DiagnosticTrace.log("SR_EVENT", p);
            }
        };
    }

    private void cleanupAfterRecognizer() {
        running = false;
        AudioRecord r = audioRecord;
        if (r != null) {
            try { r.stop(); } catch (Exception ignored) {}
        }
        pcmQueue.offer(END);
        closePipeOutput();
        destroyRecognizer();
        closeReadPfd();
    }

    private void destroyRecognizer() {
        SpeechRecognizer sr = recognizer;
        if (sr != null) {
            try {
                DiagnosticTrace.log("SR_DESTROYED", null);
                sr.destroy();
            } catch (Exception ignored) {}
            recognizer = null;
        }
    }

    private void closePipeOutput() {
        OutputStream out = pipeOutput;
        pipeOutput = null;
        if (out != null) {
            try { out.close(); } catch (Exception ignored) {}
        } else {
            ParcelFileDescriptor pfd = writePfd;
            if (pfd != null) {
                try { pfd.close(); } catch (Exception ignored) {}
            }
        }
        writePfd = null;
    }

    private void closeReadPfd() {
        ParcelFileDescriptor pfd = readPfd;
        readPfd = null;
        if (pfd != null) {
            try { pfd.close(); } catch (Exception ignored) {}
        }
    }

    private void fail(String state) {
        running = false;
        activity.runOnUiThread(() -> {
            callback.onState(state);
            callback.onResult(state);
        });
    }

    private static boolean containsWake(ArrayList<String> matches) {
        if (matches == null) return false;
        for (String s : matches) {
            String n = s.toLowerCase(Locale.ROOT).replace(" ", "").replace("-", "");
            if (n.contains("옥자") || n.contains("옥짜") || n.contains("okja")
                    || n.contains("heyokja") || n.contains("okayokja")) return true;
        }
        return false;
    }

    private static double rms(short[] x, int n) {
        double sum = 0.0;
        for (int i = 0; i < n; i++) {
            double v = x[i];
            sum += v * v;
        }
        return Math.sqrt(sum / Math.max(1, n));
    }

    private static byte[] pcm16le(short[] pcm) {
        byte[] out = new byte[pcm.length * 2];
        for (int i = 0, j = 0; i < pcm.length; i++) {
            short s = pcm[i];
            out[j++] = (byte) (s & 0xff);
            out[j++] = (byte) ((s >>> 8) & 0xff);
        }
        return out;
    }

    private static final class PcmRing {
        private final short[] data;
        private int write;
        private int size;

        PcmRing(int capacity) {
            data = new short[capacity];
        }

        void append(short[] src, int n) {
            for (int i = 0; i < n; i++) {
                data[write] = src[i];
                write = (write + 1) % data.length;
                if (size < data.length) size++;
            }
        }

        short[] snapshot() {
            short[] out = new short[size];
            int start = (write - size + data.length) % data.length;
            for (int i = 0; i < size; i++) out[i] = data[(start + i) % data.length];
            return out;
        }
    }
}
