package com.soul.aihub;

import android.content.Context;
import android.media.AudioManager;
import android.media.AudioPlaybackConfiguration;
import android.media.AudioRecordingConfiguration;
import android.os.Build;
import android.os.Handler;
import android.os.SystemClock;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileWriter;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** Lightweight structured diagnostic trace. Event timestamps are captured on the
 * calling thread, while file I/O is serialized off-thread so logging minimally
 * perturbs the wake/recognizer timing being measured. */
final class DiagnosticTrace {
    private static final Object LOCK = new Object();
    private static final ExecutorService WRITER = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "okja-diag-writer");
        t.setDaemon(true);
        return t;
    });

    private static String sessionId = "diag-" + UUID.randomUUID();
    private static String mode = "UNSET";
    private static String trialId = "";
    private static String attemptId = "";
    private static int trialCounter = 0;
    private static int attemptCounter = 0;
    private static int generation = 0;
    private static File file;
    private static AudioManager audioManager;
    private static AudioManager.AudioRecordingCallback recordingCallback;
    private static AudioManager.AudioPlaybackCallback playbackCallback;

    private DiagnosticTrace() {}

    static void init(Context context) {
        boolean firstInit = false;
        synchronized (LOCK) {
            if (file == null) {
                File root = context.getExternalFilesDir("okja-debug");
                if (root == null) root = new File(context.getFilesDir(), "okja-debug");
                if (!root.exists()) root.mkdirs();
                file = new File(root, "wake-" + System.currentTimeMillis() + ".jsonl");
                firstInit = true;
            }
        }
        if (!firstInit) return;
        JSONObject p = new JSONObject();
        try {
            p.put("sdk", Build.VERSION.SDK_INT);
            p.put("device", Build.MODEL);
            p.put("manufacturer", Build.MANUFACTURER);
            p.put("fingerprint", Build.FINGERPRINT);
        } catch (Exception ignored) {}
        log("SESSION_START", p);
        startAudioMonitors(context.getApplicationContext());
    }

    static boolean isInitialized() { synchronized (LOCK) { return file != null; } }

    static void setMode(String value) {
        synchronized (LOCK) { mode = value == null ? "UNSET" : value; }
        JSONObject p = new JSONObject();
        try { p.put("mode", value); } catch (Exception ignored) {}
        log("MODE_SELECTED", p);
    }

    static String getMode() { synchronized (LOCK) { return mode; } }

    static void beginTrial() {
        synchronized (LOCK) {
            trialCounter++;
            trialId = mode + "-" + String.format(java.util.Locale.US, "%02d", trialCounter);
            attemptCounter = 0;
            attemptId = "";
            generation = 0;
        }
        log("TRIAL_START", null);
    }

    static void beginAttempt() {
        synchronized (LOCK) {
            attemptCounter++;
            attemptId = "W" + String.format(java.util.Locale.US, "%03d", attemptCounter);
            generation = 0;
        }
        log("ATTEMPT_START", null);
    }

    static int nextGeneration() {
        synchronized (LOCK) { generation++; return generation; }
    }

    static int generation() { synchronized (LOCK) { return generation; } }
    static File currentFile() { synchronized (LOCK) { return file; } }

    static void log(String event, JSONObject payload) {
        final long timestampNs = SystemClock.elapsedRealtimeNanos();
        final String rowText;
        final File target;
        synchronized (LOCK) {
            JSONObject row = new JSONObject();
            try {
                row.put("t_ns", timestampNs);
                row.put("session_id", sessionId);
                row.put("trial_id", trialId);
                row.put("attempt_id", attemptId);
                row.put("generation", generation);
                row.put("mode", mode);
                row.put("event", event);
                if (payload != null) row.put("data", payload);
            } catch (Exception ignored) {}
            rowText = row.toString();
            target = file;
        }
        if (target == null) return;
        WRITER.execute(() -> {
            try (FileWriter out = new FileWriter(target, true)) {
                out.write(rowText);
                out.write('\n');
            } catch (Exception ignored) {}
        });
    }

    static void logCandidates(String event, List<String> values) {
        JSONObject p = new JSONObject();
        try {
            JSONArray a = new JSONArray();
            if (values != null) for (String value : values) a.put(value);
            p.put("candidates", a);
            p.put("candidate_count", values == null ? 0 : values.size());
        } catch (Exception ignored) {}
        log(event, p);
    }

    static void markBeep(String state) {
        JSONObject p = new JSONObject();
        try {
            p.put("state", state == null ? "" : state);
            p.put("human_marker", true);
        } catch (Exception ignored) {}
        log("USER_BEEP_MARK", p);
    }

    /** Flush all trace rows queued before this call. */
    static void flush(long timeoutMs) {
        try {
            WRITER.submit(() -> {}).get(timeoutMs, TimeUnit.MILLISECONDS);
        } catch (Exception ignored) {}
    }

    private static void startAudioMonitors(Context context) {
        try {
            audioManager = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            if (audioManager == null) return;
            Handler handler = new Handler(context.getMainLooper());
            recordingCallback = new AudioManager.AudioRecordingCallback() {
                @Override public void onRecordingConfigChanged(List<AudioRecordingConfiguration> configs) {
                    JSONObject p = new JSONObject();
                    JSONArray items = new JSONArray();
                    try {
                        p.put("active_count", configs == null ? 0 : configs.size());
                        if (configs != null) for (AudioRecordingConfiguration c : configs) {
                            JSONObject x = new JSONObject();
                            x.put("client_session_id", c.getClientAudioSessionId());
                            x.put("client_source", c.getClientAudioSource());
                            x.put("client_sample_rate", c.getClientFormat().getSampleRate());
                            x.put("actual_sample_rate", c.getFormat().getSampleRate());
                            if (Build.VERSION.SDK_INT >= 29) {
                                x.put("actual_source", c.getAudioSource());
                                x.put("client_silenced", c.isClientSilenced());
                            }
                            if (c.getAudioDevice() != null) {
                                x.put("device_id", c.getAudioDevice().getId());
                                x.put("device_type", c.getAudioDevice().getType());
                            }
                            items.put(x);
                        }
                        p.put("configs", items);
                    } catch (Exception e) {
                        try { p.put("read_error", e.getClass().getSimpleName()); } catch (Exception ignored) {}
                    }
                    log("RECORDING_CONFIG_CHANGED", p);
                }
            };
            playbackCallback = new AudioManager.AudioPlaybackCallback() {
                @Override public void onPlaybackConfigChanged(List<AudioPlaybackConfiguration> configs) {
                    JSONObject p = new JSONObject();
                    JSONArray items = new JSONArray();
                    try {
                        p.put("reported_count", configs == null ? 0 : configs.size());
                        if (configs != null) for (AudioPlaybackConfiguration c : configs) {
                            JSONObject x = new JSONObject();
                            x.put("usage", c.getAudioAttributes().getUsage());
                            x.put("content_type", c.getAudioAttributes().getContentType());
                            x.put("flags", c.getAudioAttributes().getFlags());
                            if (Build.VERSION.SDK_INT >= 31 && c.getAudioDeviceInfo() != null) {
                                x.put("device_id", c.getAudioDeviceInfo().getId());
                                x.put("device_type", c.getAudioDeviceInfo().getType());
                            }
                            items.put(x);
                        }
                        p.put("configs", items);
                    } catch (Exception e) {
                        try { p.put("read_error", e.getClass().getSimpleName()); } catch (Exception ignored) {}
                    }
                    log("PLAYBACK_CONFIG_CHANGED", p);
                }
            };
            audioManager.registerAudioRecordingCallback(recordingCallback, handler);
            audioManager.registerAudioPlaybackCallback(playbackCallback, handler);
            log("AUDIO_MONITORS_REGISTERED", null);
        } catch (Exception e) {
            JSONObject p = new JSONObject();
            try { p.put("error", e.getClass().getSimpleName()); } catch (Exception ignored) {}
            log("AUDIO_MONITOR_FAILED", p);
        }
    }
}
