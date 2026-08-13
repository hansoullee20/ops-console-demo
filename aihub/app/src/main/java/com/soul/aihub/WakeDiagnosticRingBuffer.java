package com.soul.aihub;

import org.json.JSONObject;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.FileWriter;
import java.io.IOException;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/**
 * Privacy-first in-memory PCM16 diagnostic ring buffer.
 *
 * Continuous microphone audio is never written by feed(). A short WAV is
 * persisted only after markCandidate() or markManualMiss(), with configured
 * pre/post-roll and one JSONL metadata row.
 */
public final class WakeDiagnosticRingBuffer {
    public static final int DEFAULT_SAMPLE_RATE = 16000;
    public static final int DEFAULT_PRE_MS = 3000;
    public static final int DEFAULT_POST_MS = 2000;

    private final File outputDir;
    private final int sampleRate;
    private final short[] ring;
    private final int postSamples;
    private final List<PendingCapture> pending = new ArrayList<>();

    private int ringPos = 0;
    private int ringSize = 0;

    public WakeDiagnosticRingBuffer(File outputDir) {
        this(outputDir, DEFAULT_SAMPLE_RATE, DEFAULT_PRE_MS, DEFAULT_POST_MS);
    }

    public WakeDiagnosticRingBuffer(File outputDir, int sampleRate, int preMs, int postMs) {
        if (outputDir == null) throw new IllegalArgumentException("outputDir required");
        if (sampleRate <= 0 || preMs <= 0 || postMs < 0) {
            throw new IllegalArgumentException("invalid sample rate/pre/post duration");
        }
        this.outputDir = outputDir;
        this.sampleRate = sampleRate;
        this.ring = new short[Math.max(1, sampleRate * preMs / 1000)];
        this.postSamples = Math.max(0, sampleRate * postMs / 1000);
    }

    /** Feed microphone PCM. This method performs no disk I/O unless a capture is pending. */
    public synchronized void feed(short[] samples, int count) {
        if (samples == null || count <= 0) return;
        int n = Math.min(count, samples.length);

        if (!pending.isEmpty()) {
            for (int p = pending.size() - 1; p >= 0; p--) {
                PendingCapture capture = pending.get(p);
                int take = Math.min(n, capture.remainingPostSamples);
                for (int i = 0; i < take; i++) capture.pcm.add(samples[i]);
                capture.remainingPostSamples -= take;
                if (capture.remainingPostSamples <= 0) {
                    pending.remove(p);
                    try {
                        persist(capture);
                    } catch (Exception ignored) {
                        // Diagnostics must never crash the wake detector.
                    }
                }
            }
        }

        for (int i = 0; i < n; i++) {
            ring[ringPos] = samples[i];
            ringPos = (ringPos + 1) % ring.length;
            if (ringSize < ring.length) ringSize++;
        }
    }

    /** Capture accepted or near-threshold candidate audio. */
    public synchronized String markCandidate(double score, double threshold, boolean accepted,
                                             String modelName, String modelVersion, String modelSha) {
        return markCandidate(score, threshold, accepted,
                modelName, modelVersion, modelSha, null);
    }

    /** Capture a candidate with additional structured diagnostic metadata. */
    public synchronized String markCandidate(double score, double threshold, boolean accepted,
                                             String modelName, String modelVersion, String modelSha,
                                             JSONObject additionalMetadata) {
        JSONObject metadata = new JSONObject();
        try {
            if (additionalMetadata != null) {
                Iterator<String> keys = additionalMetadata.keys();
                while (keys.hasNext()) {
                    String key = keys.next();
                    metadata.put(key, additionalMetadata.get(key));
                }
            }
            // Identity fields are reserved and cannot be replaced by extensions.
            metadata.put("model_name", safe(modelName));
            metadata.put("model_version", safe(modelVersion));
            metadata.put("model_sha", safe(modelSha));
        } catch (Exception ignored) {}
        return start("candidate", score, threshold, accepted, metadata);
    }

    /** Capture a user-marked wake that the active detector missed. */
    public synchronized String markManualMiss(String phrase, String note) {
        JSONObject metadata = new JSONObject();
        try {
            metadata.put("phrase", safe(phrase));
            metadata.put("note", safe(note));
            metadata.put("reason", "user_marked_missed_wake");
        } catch (Exception ignored) {}
        return start("manual_miss", null, null, null, metadata);
    }

    /** Finalize any pending captures early when the detector stops. */
    public synchronized void flushPending() {
        List<PendingCapture> copy = new ArrayList<>(pending);
        pending.clear();
        for (PendingCapture capture : copy) {
            try {
                persist(capture);
            } catch (Exception ignored) {}
        }
    }

    public synchronized int getBufferedSamples() {
        return ringSize;
    }

    public synchronized int getPendingCaptureCount() {
        return pending.size();
    }

    private String start(String kind, Double score, Double threshold, Boolean accepted, JSONObject metadata) {
        String eventId = "diag-" + UUID.randomUUID();
        ArrayList<Short> pcm = snapshotPreRoll();
        PendingCapture capture = new PendingCapture(
                eventId, kind, score, threshold, accepted, metadata, pcm, postSamples,
                android.os.SystemClock.elapsedRealtime());
        if (postSamples == 0) {
            try { persist(capture); } catch (Exception ignored) {}
        } else {
            pending.add(capture);
        }
        return eventId;
    }

    private ArrayList<Short> snapshotPreRoll() {
        ArrayList<Short> out = new ArrayList<>(ringSize + postSamples);
        int start = (ringPos - ringSize + ring.length) % ring.length;
        for (int i = 0; i < ringSize; i++) out.add(ring[(start + i) % ring.length]);
        return out;
    }

    private void persist(PendingCapture capture) throws Exception {
        if (!outputDir.exists() && !outputDir.mkdirs()) {
            throw new IOException("cannot create diagnostic output dir");
        }
        File wav = new File(outputDir, capture.eventId + ".wav");
        writeWav(wav, capture.pcm, sampleRate);
        String digest = sha256(wav);

        JSONObject row = new JSONObject();
        row.put("schema_version", 1);
        row.put("event_id", capture.eventId);
        row.put("kind", capture.kind);
        row.put("created_monotonic_ms", capture.createdMonotonicMs);
        row.put("sample_rate_hz", sampleRate);
        row.put("channels", 1);
        row.put("pre_samples_configured", ring.length);
        row.put("post_samples_configured", postSamples);
        row.put("saved_samples", capture.pcm.size());
        row.put("wav_filename", wav.getName());
        row.put("audio_sha256", digest);
        row.put("score", capture.score == null ? JSONObject.NULL : capture.score);
        row.put("threshold", capture.threshold == null ? JSONObject.NULL : capture.threshold);
        row.put("accepted", capture.accepted == null ? JSONObject.NULL : capture.accepted);
        row.put("metadata", capture.metadata);

        File events = new File(outputDir, "wake_diagnostic_events.jsonl");
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(events, true))) {
            writer.write(row.toString());
            writer.newLine();
        }
    }

    private static void writeWav(File file, List<Short> pcm, int sampleRate) throws IOException {
        int dataBytes = pcm.size() * 2;
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(new byte[]{'R','I','F','F'});
            writeLe32(out, 36 + dataBytes);
            out.write(new byte[]{'W','A','V','E'});
            out.write(new byte[]{'f','m','t',' '});
            writeLe32(out, 16);
            writeLe16(out, 1); // PCM
            writeLe16(out, 1); // mono
            writeLe32(out, sampleRate);
            writeLe32(out, sampleRate * 2);
            writeLe16(out, 2);
            writeLe16(out, 16);
            out.write(new byte[]{'d','a','t','a'});
            writeLe32(out, dataBytes);
            for (short s : pcm) writeLe16(out, s & 0xffff);
        }
    }

    private static void writeLe16(FileOutputStream out, int v) throws IOException {
        out.write(v & 0xff);
        out.write((v >>> 8) & 0xff);
    }

    private static void writeLe32(FileOutputStream out, int v) throws IOException {
        out.write(v & 0xff);
        out.write((v >>> 8) & 0xff);
        out.write((v >>> 16) & 0xff);
        out.write((v >>> 24) & 0xff);
    }

    private static String sha256(File file) throws Exception {
        MessageDigest md = MessageDigest.getInstance("SHA-256");
        try (java.io.FileInputStream in = new java.io.FileInputStream(file)) {
            byte[] buffer = new byte[8192];
            int n;
            while ((n = in.read(buffer)) > 0) md.update(buffer, 0, n);
        }
        byte[] digest = md.digest();
        StringBuilder sb = new StringBuilder(64);
        for (byte b : digest) sb.append(String.format(Locale.US, "%02x", b & 0xff));
        return sb.toString();
    }

    private static String safe(String value) {
        return value == null ? "" : value;
    }

    private static final class PendingCapture {
        final String eventId;
        final String kind;
        final Double score;
        final Double threshold;
        final Boolean accepted;
        final JSONObject metadata;
        final ArrayList<Short> pcm;
        int remainingPostSamples;
        final long createdMonotonicMs;

        PendingCapture(String eventId, String kind, Double score, Double threshold, Boolean accepted,
                       JSONObject metadata, ArrayList<Short> pcm, int remainingPostSamples,
                       long createdMonotonicMs) {
            this.eventId = eventId;
            this.kind = kind;
            this.score = score;
            this.threshold = threshold;
            this.accepted = accepted;
            this.metadata = metadata;
            this.pcm = pcm;
            this.remainingPostSamples = remainingPostSamples;
            this.createdMonotonicMs = createdMonotonicMs;
        }
    }
}
