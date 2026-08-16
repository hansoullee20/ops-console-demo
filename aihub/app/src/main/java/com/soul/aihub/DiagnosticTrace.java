package com.soul.aihub;

import android.content.Context;
import android.media.AudioManager;
import android.media.AudioPlaybackConfiguration;
import android.media.AudioRecordingConfiguration;
import android.os.Handler;
import android.os.SystemClock;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileWriter;
import java.util.List;
import java.util.UUID;

final class DiagnosticTrace {
    private static final Object LOCK = new Object();
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
        synchronized (LOCK) {
            if (file != null) return;
            File root = context.getExternalFilesDir("okja-debug");
            if (root == null) root = new File(context.getFilesDir(), "okja-debug");
            if (!root.exists()) root.mkdirs();
            file = new File(root, "wake-" + System.currentTimeMillis() + ".jsonl");
        }
        JSONObject p = new JSONObject();
        try { p.put("sdk", android.os.Build.VERSION.SDK_INT); p.put("device", android.os.Build.MODEL); p.put("manufacturer", android.os.Build.MANUFACTURER); } catch (Exception ignored) {}
        log("SESSION_START", p);
        startAudioMonitors(context);
    }

    static void setMode(String value) {
        synchronized (LOCK) { mode = value == null ? "UNSET" : value; }
        JSONObject p = new JSONObject(); try { p.put("mode", value); } catch (Exception ignored) {}
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
        JSONObject row = new JSONObject();
        synchronized (LOCK) {
            try {
                row.put("t_ns", SystemClock.elapsedRealtimeNanos());
                row.put("session_id", sessionId);
                row.put("trial_id", trialId);
                row.put("attempt_id", attemptId);
                row.put("generation", generation);
                row.put("mode", mode);
                row.put("event", event);
                if (payload != null) row.put("data", payload);
                if (file != null) {
                    try (FileWriter out = new FileWriter(file, true)) {
                        out.write(row.toString());
                        out.write('\n');
                    }
                }
            } catch (Exception ignored) {}
        }
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
        try { p.put("state", state == null ? "" : state); } catch (Exception ignored) {}
        log("USER_BEEP_MARK", p);
    }

    private static void startAudioMonitors(Context context) {
        try {
            audioManager = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            if (audioManager == null) return;
            Handler handler = new Handler(context.getMainLooper());
            recordingCallback = new AudioManager.AudioRecordingCallback() {
                @Override public void onRecordingConfigChanged(List<AudioRecordingConfiguration> configs) {
                    JSONObject p = new JSONObject(); JSONArray items = new JSONArray();
                    try {
                        p.put("active_count", configs == null ? 0 : configs.size());
                        if (configs != null) for (AudioRecordingConfiguration c : configs) {
                            JSONObject x = new JSONObject();
                            x.put("client_source", c.getClientAudioSource());
                            x.put("actual_source", c.getAudioSource());
                            x.put("client_sample_rate", c.getClientFormat().getSampleRate());
                            x.put("actual_sample_rate", c.getFormat().getSampleRate());
                            x.put("client_silenced", c.isClientSilenced());
                            if (c.getAudioDevice() != null) { x.put("device_id", c.getAudioDevice().getId()); x.put("device_type", c.getAudioDevice().getType()); }
                            items.put(x);
                        }
                        p.put("configs", items);
                    } catch (Exception e) { try { p.put("read_error", e.getClass().getSimpleName()); } catch (Exception ignored) {} }
                    log("RECORDING_CONFIG_CHANGED", p);
                }
            };
            playbackCallback = new AudioManager.AudioPlaybackCallback() {
                @Override public void onPlaybackConfigChanged(List<AudioPlaybackConfiguration> configs) {
                    JSONObject p = new JSONObject(); JSONArray items = new JSONArray();
                    try {
                        p.put("active_count", configs == null ? 0 : configs.size());
                        if (configs != null) for (AudioPlaybackConfiguration c : configs) {
                            JSONObject x = new JSONObject();
                            x.put("state", c.getPlayerState());
                            x.put("usage", c.getAudioAttributes().getUsage());
                            x.put("sample_rate", c.getAudioFormat().getSampleRate());
                            items.put(x);
                        }
                        p.put("configs", items);
                    } catch (Exception e) { try { p.put("read_error", e.getClass().getSimpleName()); } catch (Exception ignored) {} }
                    log("PLAYBACK_CONFIG_CHANGED", p);
                }
            };
            audioManager.registerAudioRecordingCallback(recordingCallback, handler);
            audioManager.registerAudioPlaybackCallback(playbackCallback, handler);
        } catch (Exception e) {
            JSONObject p = new JSONObject(); try { p.put("error", e.getClass().getSimpleName()); } catch (Exception ignored) {}
            log("AUDIO_MONITOR_FAILED", p);
        }
    }
}
