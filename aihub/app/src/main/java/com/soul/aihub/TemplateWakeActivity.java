package com.soul.aihub;

import android.app.Activity;
import android.graphics.Color;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.AudioManager;
import android.media.MediaRecorder;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Bundle;
import android.os.Debug;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import android.os.SystemClock;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

import org.json.JSONObject;

/**
 * Experimental zero-cost wake detector.
 *
 * No ASR and no cloud are used while waiting. The user records a few reference
 * utterances and we compare short speech segments with MFCC + DTW.
 * This is intentionally a test harness: if accuracy/CPU are good we can wire
 * the detection callback into the normal Claude command flow.
 */
public class TemplateWakeActivity extends Activity {
    private static final int SAMPLE_RATE = 16000;
    private static final int FRAME = 320;          // 20 ms
    private static final int PRE_ROLL = 2400;      // 150 ms
    private static final int MAX_SEGMENT = 48000;  // 3 s
    private static final int MIN_SEGMENT = 5200;   // 325 ms
    private static final int TEMPLATE_COUNT = 6;
    private static final double DIAGNOSTIC_NEAR_THRESHOLD_MULTIPLIER = 1.25;
    private static final String DIAGNOSTIC_MODEL_NAME = "template_mfcc_dtw";
    private static final String DIAGNOSTIC_MODEL_VERSION = "android-v1";

    private static final String[] PROMPTS = {
            "옥자야", "옥자야", "옥자", "옥자", "Hey Okja", "Hey Okja"
    };

    private final Handler main = new Handler(Looper.getMainLooper());
    private final List<Template> templates = new ArrayList<>();
    private final List<Long> acceptedWakeLatenciesMs = new ArrayList<>();

    private TextView stateText;
    private TextView scoreText;
    private TextView perfText;
    private Button enrollButton;
    private Button detectButton;
    private Button resetButton;
    private Button missButton;
    private WakeDiagnosticRingBuffer diagnostics;

    private volatile boolean detectorRunning = false;
    private volatile boolean recordingTemplate = false;
    private Thread detectorThread;
    private AudioRecord activeRecorder;
    private int enrolled = 0;
    private int detections = 0;
    private double threshold = 4.0;
    private long cooldownUntil = 0;
    private String diagnosticSessionId = "";
    private String diagnosticModelSha = "";

    private long perfStarted;
    private long perfWall;
    private long perfCpu;

    private final Runnable perfTick = new Runnable() {
        @Override public void run() {
            updatePerf();
            main.postDelayed(this, 2000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        loadTemplates();
        refreshUi();

        perfStarted = SystemClock.elapsedRealtime();
        perfWall = perfStarted;
        perfCpu = Process.getElapsedCpuTime();
        main.post(perfTick);
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(36, 46, 36, 36);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.rgb(18, 18, 20));

        TextView title = text("옥자 · 로컬 웨이크 실험", 28, Color.WHITE);
        stateText = text("준비 중", 20, Color.LTGRAY);
        scoreText = text("", 17, Color.rgb(190, 220, 255));
        perfText = text("", 14, Color.rgb(160, 255, 180));

        TextView help = text(
                "처음 한 번만 6회 등록합니다.\n등록 중 화면에 나온 말을 자연스럽게 한 번 말하세요.\n대기 중에는 STT/인터넷을 쓰지 않습니다.",
                16, Color.LTGRAY);

        enrollButton = button("다음 샘플 등록");
        enrollButton.setOnClickListener(v -> enrollNext());

        detectButton = button("로컬 감지 시작");
        detectButton.setOnClickListener(v -> {
            if (detectorRunning) stopDetector();
            else startDetector();
        });

        resetButton = button("등록 초기화");
        resetButton.setOnClickListener(v -> resetTemplates());

        missButton = button("방금 옥자를 놓쳤어 · 진단 저장");
        missButton.setOnClickListener(v -> markManualMiss());

        root.addView(title, full());
        root.addView(space(14));
        root.addView(stateText, full());
        root.addView(space(16));
        root.addView(help, full());
        root.addView(space(22));
        root.addView(enrollButton, full());
        root.addView(space(10));
        root.addView(detectButton, full());
        root.addView(space(10));
        root.addView(missButton, full());
        root.addView(space(10));
        root.addView(resetButton, full());
        root.addView(space(26));
        root.addView(scoreText, full());
        root.addView(space(18));
        root.addView(perfText, full());

        setContentView(root);
    }

    private TextView text(String s, float sp, int color) {
        TextView v = new TextView(this);
        v.setText(s);
        v.setTextSize(sp);
        v.setTextColor(color);
        v.setGravity(Gravity.CENTER);
        v.setPadding(6, 6, 6, 6);
        return v;
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setAllCaps(false);
        b.setTextSize(18);
        b.setText(label);
        return b;
    }

    private LinearLayout.LayoutParams full() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private android.view.View space(int h) {
        android.view.View v = new android.view.View(this);
        v.setLayoutParams(new LinearLayout.LayoutParams(1, h));
        return v;
    }

    private File templateFile(int i) {
        return new File(getFilesDir(), "okja_template_" + i + ".pcm16");
    }

    private void loadTemplates() {
        templates.clear();
        acceptedWakeLatenciesMs.clear();
        enrolled = 0;
        for (int i = 0; i < TEMPLATE_COUNT; i++) {
            File f = templateFile(i);
            if (!f.exists()) break;
            try (DataInputStream in = new DataInputStream(new FileInputStream(f))) {
                int n = in.readInt();
                if (n < 1000 || n > MAX_SEGMENT * 2) throw new IllegalStateException("bad template");
                short[] pcm = new short[n];
                for (int j = 0; j < n; j++) pcm[j] = in.readShort();
                double[][] feat = Mfcc.extract(pcm);
                if (feat.length < 8) throw new IllegalStateException("short feature");
                templates.add(new Template(PROMPTS[i], pcm.length, feat));
                enrolled++;
            } catch (Exception e) {
                f.delete();
                break;
            }
        }
        calibrateThreshold();
    }

    private void saveTemplate(int index, short[] pcm) throws Exception {
        try (DataOutputStream out = new DataOutputStream(new FileOutputStream(templateFile(index)))) {
            out.writeInt(pcm.length);
            for (short s : pcm) out.writeShort(s);
        }
    }

    private void enrollNext() {
        if (recordingTemplate || detectorRunning || enrolled >= TEMPLATE_COUNT) return;
        recordingTemplate = true;
        enrollButton.setEnabled(false);
        detectButton.setEnabled(false);
        final int index = enrolled;
        stateText.setText("준비… 1초 뒤 \"" + PROMPTS[index] + "\"");

        main.postDelayed(() -> {
            stateText.setText("지금 말하세요:  \"" + PROMPTS[index] + "\"");
            new Thread(() -> recordOneTemplate(index), "okja-enroll").start();
        }, 900);
    }

    private void recordOneTemplate(int index) {
        short[] pcm = recordFixed(1900);
        String message;
        try {
            short[] trimmed = Mfcc.trim(pcm);
            if (trimmed.length < MIN_SEGMENT) throw new IllegalStateException("너무 짧음");
            saveTemplate(index, trimmed);
            double[][] feat = Mfcc.extract(trimmed);
            templates.add(new Template(PROMPTS[index], trimmed.length, feat));
            enrolled++;
            calibrateThreshold();
            message = "등록 완료 " + enrolled + "/" + TEMPLATE_COUNT;
        } catch (Exception e) {
            message = "등록 실패 · 다시 말해주세요";
        }

        final String msg = message;
        recordingTemplate = false;
        main.post(() -> {
            stateText.setText(msg);
            refreshUi();
        });
    }

    private short[] recordFixed(int durationMs) {
        int wanted = SAMPLE_RATE * durationMs / 1000;
        int min = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        int bufferBytes = Math.max(min, 4096);
        AudioRecord rec = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufferBytes);
        activeRecorder = rec;
        short[] out = new short[wanted];
        int pos = 0;
        try {
            rec.startRecording();
            while (pos < wanted && recordingTemplate) {
                int n = rec.read(out, pos, Math.min(1024, wanted - pos));
                if (n > 0) pos += n;
            }
        } catch (Exception ignored) {
        } finally {
            try { rec.stop(); } catch (Exception ignored) {}
            rec.release();
            activeRecorder = null;
        }
        return pos == out.length ? out : Arrays.copyOf(out, Math.max(0, pos));
    }

    private void resetTemplates() {
        stopDetector();
        for (int i = 0; i < TEMPLATE_COUNT; i++) templateFile(i).delete();
        templates.clear();
        enrolled = 0;
        detections = 0;
        threshold = 4.0;
        scoreText.setText("");
        stateText.setText("등록 초기화 완료");
        refreshUi();
    }

    private void refreshUi() {
        if (enrolled < TEMPLATE_COUNT) {
            enrollButton.setText("등록 " + (enrolled + 1) + "/" + TEMPLATE_COUNT + " · \"" + PROMPTS[enrolled] + "\"");
            enrollButton.setEnabled(!recordingTemplate && !detectorRunning);
            detectButton.setEnabled(false);
        } else {
            enrollButton.setText("등록 완료");
            enrollButton.setEnabled(false);
            detectButton.setEnabled(!recordingTemplate);
            if (!detectorRunning) stateText.setText("준비됨 · 로컬 감지 가능");
        }
        detectButton.setText(detectorRunning ? "로컬 감지 중지" : "로컬 감지 시작");
        resetButton.setEnabled(!recordingTemplate);
        if (missButton != null) missButton.setEnabled(detectorRunning && !recordingTemplate);
        if (enrolled >= 2 && !detectorRunning) {
            scoreText.setText(String.format(Locale.US, "자동 임계값 %.2f · 등록 %d개", threshold, enrolled));
        }
    }

    private void markManualMiss() {
        if (!detectorRunning || diagnostics == null) {
            stateText.setText("로컬 감지 중에만 누락 샘플을 저장할 수 있어요");
            return;
        }
        String eventId = diagnostics.markManualMiss("옥자", "manual_button");
        String shortId = eventId.length() > 13 ? eventId.substring(0, 13) : eventId;
        stateText.setText("누락 진단 캡처 중 · " + shortId);
        main.postDelayed(() -> {
            if (detectorRunning) {
                stateText.setText("로컬 대기 중 · 옥자 / 옥자야 / Hey Okja");
            }
        }, 2200);
    }

    private void calibrateThreshold() {
        if (templates.size() < 2) return;
        List<Double> pair = new ArrayList<>();
        for (int i = 0; i < templates.size(); i++) {
            for (int j = i + 1; j < templates.size(); j++) {
                if (!templates.get(i).phrase.equals(templates.get(j).phrase)) continue;
                pair.add(Mfcc.dtw(templates.get(i).features, templates.get(j).features));
            }
        }
        if (pair.isEmpty()) return;
        Collections.sort(pair);
        double median = pair.get(pair.size() / 2);
        threshold = clamp(median * 1.55, 1.35, 7.5);
    }

    private static double clamp(double x, double lo, double hi) {
        return Math.max(lo, Math.min(hi, x));
    }

    private void startDetector() {
        if (detectorRunning || recordingTemplate || templates.size() < TEMPLATE_COUNT) return;
        diagnosticModelSha = templateSetSha256();
        if (diagnosticModelSha.isEmpty()) {
            stateText.setText("등록 샘플 지문 생성 실패");
            return;
        }
        diagnosticSessionId = "wake-latency-" + UUID.randomUUID();
        acceptedWakeLatenciesMs.clear();
        diagnostics = new WakeDiagnosticRingBuffer(new File(getFilesDir(), "wake_diagnostics"));
        detectorRunning = true;
        detections = 0;
        cooldownUntil = 0;
        stateText.setText("로컬 대기 중 · 옥자 / 옥자야 / Hey Okja");
        refreshUi();
        detectorThread = new Thread(this::detectorLoop, "okja-local-detector");
        detectorThread.start();
    }

    private void stopDetector() {
        detectorRunning = false;
        AudioRecord r = activeRecorder;
        if (r != null) {
            try { r.stop(); } catch (Exception ignored) {}
        }
        Thread t = detectorThread;
        if (t != null) {
            try { t.join(500); } catch (InterruptedException ignored) {}
        }
        detectorThread = null;
        WakeDiagnosticRingBuffer d = diagnostics;
        if (d != null) d.flushPending();
        main.post(() -> {
            stateText.setText("로컬 감지 중지됨");
            refreshUi();
        });
    }

    private void detectorLoop() {
        int min = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        AudioRecord rec = new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                Math.max(min, 8192));
        activeRecorder = rec;

        short[] frame = new short[FRAME];
        short[] pre = new short[PRE_ROLL];
        int prePos = 0;
        short[] segment = new short[MAX_SEGMENT];
        int segLen = 0;
        boolean speaking = false;
        long speechStartedMonotonicMs = 0;
        int silenceFrames = 0;
        double noise = 250.0;

        try {
            rec.startRecording();
            while (detectorRunning) {
                int got = readFully(rec, frame);
                if (got <= 0) continue;
                WakeDiagnosticRingBuffer d = diagnostics;
                if (d != null) d.feed(frame, got);
                double rms = rms(frame, got);

                for (int i = 0; i < got; i++) {
                    pre[prePos] = frame[i];
                    prePos = (prePos + 1) % pre.length;
                }

                if (!speaking) {
                    noise = noise * 0.985 + Math.min(rms, noise * 2.0) * 0.015;
                }
                double voiceThreshold = Math.max(420.0, noise * 2.7);
                boolean voiced = rms > voiceThreshold;

                if (!speaking && voiced) {
                    speaking = true;
                    long frameDurationMs = Math.round(got * 1000.0 / SAMPLE_RATE);
                    speechStartedMonotonicMs = Math.max(
                            0L, SystemClock.elapsedRealtime() - frameDurationMs);
                    segLen = 0;
                    silenceFrames = 0;
                    int start = prePos;
                    for (int i = 0; i < pre.length && segLen < segment.length; i++) {
                        segment[segLen++] = pre[(start + i) % pre.length];
                    }
                }

                if (speaking) {
                    for (int i = 0; i < got && segLen < segment.length; i++) segment[segLen++] = frame[i];
                    if (voiced || rms > voiceThreshold * 0.72) silenceFrames = 0;
                    else silenceFrames++;

                    boolean end = silenceFrames >= 15 || segLen >= segment.length;
                    if (end) {
                        if (segLen >= MIN_SEGMENT && SystemClock.elapsedRealtime() >= cooldownUntil) {
                            evaluate(Arrays.copyOf(segment, segLen),
                                    speechStartedMonotonicMs, SystemClock.elapsedRealtime());
                        }
                        speaking = false;
                        speechStartedMonotonicMs = 0;
                        segLen = 0;
                        silenceFrames = 0;
                    }
                }
            }
        } catch (Exception e) {
            main.post(() -> stateText.setText("로컬 마이크 오류: " + e.getClass().getSimpleName()));
        } finally {
            try { rec.stop(); } catch (Exception ignored) {}
            rec.release();
            activeRecorder = null;
        }
    }

    private int readFully(AudioRecord rec, short[] frame) {
        int pos = 0;
        while (pos < frame.length && detectorRunning) {
            int n = rec.read(frame, pos, frame.length - pos);
            if (n <= 0) return n;
            pos += n;
        }
        return pos;
    }

    private void evaluate(short[] raw, long speechStartedMonotonicMs,
                          long segmentEndedMonotonicMs) {
        short[] pcm = Mfcc.trim(raw);
        if (pcm.length < MIN_SEGMENT) return;
        double[][] feat = Mfcc.extract(pcm);
        if (feat.length < 8) return;

        List<Double> distances = new ArrayList<>();
        for (Template t : templates) {
            double durationRatio = pcm.length / (double) t.samples;
            if (durationRatio < 0.48 || durationRatio > 2.15) continue;
            distances.add(Mfcc.dtw(feat, t.features));
        }
        if (distances.isEmpty()) return;
        Collections.sort(distances);
        double best = distances.get(0);
        double score = distances.size() >= 2 ? (best * 0.65 + distances.get(1) * 0.35) : best;
        boolean hit = score <= threshold;
        long decisionMonotonicMs = SystemClock.elapsedRealtime();
        long wakeLatencyMs = Math.max(0L, decisionMonotonicMs - speechStartedMonotonicMs);
        long postSegmentProcessingMs = Math.max(0L, decisionMonotonicMs - segmentEndedMonotonicMs);

        WakeDiagnosticRingBuffer d = diagnostics;
        if (d != null && (hit || score <= threshold * DIAGNOSTIC_NEAR_THRESHOLD_MULTIPLIER)) {
            JSONObject latencyMetadata = new JSONObject();
            try {
                latencyMetadata.put("latency_schema_version", 1);
                latencyMetadata.put("latency_definition", "vad_onset_to_decision_monotonic");
                latencyMetadata.put("measurement_clock", "android.os.SystemClock.elapsedRealtime");
                latencyMetadata.put("session_id", diagnosticSessionId);
                latencyMetadata.put("vad_onset_monotonic_ms", speechStartedMonotonicMs);
                latencyMetadata.put("segment_end_monotonic_ms", segmentEndedMonotonicMs);
                latencyMetadata.put("decision_monotonic_ms", decisionMonotonicMs);
                latencyMetadata.put("segment_duration_ms",
                        Math.max(0L, segmentEndedMonotonicMs - speechStartedMonotonicMs));
                latencyMetadata.put("wake_latency_ms", wakeLatencyMs);
                latencyMetadata.put("post_segment_processing_ms", postSegmentProcessingMs);
                latencyMetadata.put("device_manufacturer", Build.MANUFACTURER);
                latencyMetadata.put("device_model", Build.MODEL);
                latencyMetadata.put("device_sdk_int", Build.VERSION.SDK_INT);
                latencyMetadata.put("device_fingerprint", Build.FINGERPRINT);
                latencyMetadata.put("app_version", appVersionName());
            } catch (Exception ignored) {}
            d.markCandidate(score, threshold, hit,
                    DIAGNOSTIC_MODEL_NAME, DIAGNOSTIC_MODEL_VERSION,
                    diagnosticModelSha, latencyMetadata);
        }

        String latencySummary = "";
        if (hit) {
            acceptedWakeLatenciesMs.add(wakeLatencyMs);
            latencySummary = String.format(Locale.US,
                    "\nlatency %d ms · P50 %.0f · P95 %.0f · n=%d",
                    wakeLatencyMs,
                    percentile(acceptedWakeLatenciesMs, 0.50),
                    percentile(acceptedWakeLatenciesMs, 0.95),
                    acceptedWakeLatenciesMs.size());
        }
        final String latencyLine = latencySummary;
        main.post(() -> scoreText.setText(String.format(Locale.US,
                "%s · distance %.2f / %.2f · 감지 %d회%s",
                hit ? "MATCH" : "skip", score, threshold,
                detections + (hit ? 1 : 0), latencyLine)));

        if (hit) {
            cooldownUntil = SystemClock.elapsedRealtime() + 1800;
            detections++;
            main.post(() -> {
                stateText.setText("✅ 옥자 감지 · " + detections + "회");
                try {
                    ToneGenerator tone = new ToneGenerator(AudioManager.STREAM_NOTIFICATION, 65);
                    tone.startTone(ToneGenerator.TONE_PROP_BEEP, 120);
                    main.postDelayed(tone::release, 180);
                } catch (Exception ignored) {}
                main.postDelayed(() -> {
                    if (detectorRunning) stateText.setText("로컬 대기 중 · 옥자 / 옥자야 / Hey Okja");
                }, 900);
            });
        }
    }

    private String templateSetSha256() {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[8192];
            for (int i = 0; i < TEMPLATE_COUNT; i++) {
                md.update((byte) i);
                try (FileInputStream in = new FileInputStream(templateFile(i))) {
                    int n;
                    while ((n = in.read(buffer)) > 0) md.update(buffer, 0, n);
                }
            }
            StringBuilder out = new StringBuilder(64);
            for (byte b : md.digest()) {
                out.append(String.format(Locale.US, "%02x", b & 0xff));
            }
            return out.toString();
        } catch (Exception ignored) {
            return "";
        }
    }

    private String appVersionName() {
        try {
            String versionName = getPackageManager()
                    .getPackageInfo(getPackageName(), 0).versionName;
            return versionName == null || versionName.isEmpty() ? "unknown" : versionName;
        } catch (Exception ignored) {
            return "unknown";
        }
    }

    private static double percentile(List<Long> values, double p) {
        if (values.isEmpty()) return Double.NaN;
        List<Long> sorted = new ArrayList<>(values);
        Collections.sort(sorted);
        if (sorted.size() == 1) return sorted.get(0);
        double index = (sorted.size() - 1) * p;
        int lo = (int) Math.floor(index);
        int hi = (int) Math.ceil(index);
        if (lo == hi) return sorted.get(lo);
        return sorted.get(lo) + (sorted.get(hi) - sorted.get(lo)) * (index - lo);
    }

    private static double rms(short[] x, int n) {
        double s = 0;
        for (int i = 0; i < n; i++) {
            double v = x[i];
            s += v * v;
        }
        return Math.sqrt(s / Math.max(1, n));
    }

    private void updatePerf() {
        if (perfText == null) return;
        long now = SystemClock.elapsedRealtime();
        long cpu = Process.getElapsedCpuTime();
        long dw = Math.max(1, now - perfWall);
        long dc = Math.max(0, cpu - perfCpu);
        double cpuPct = dc * 100.0 / dw;
        double pssMb = Debug.getPss() / 1024.0;
        Runtime rt = Runtime.getRuntime();
        double javaMb = (rt.totalMemory() - rt.freeMemory()) / (1024.0 * 1024.0);
        long up = (now - perfStarted) / 1000;
        perfText.setText(String.format(Locale.US,
                "PERF · %02d:%02d · app CPU %.1f%% · PSS %.1f MB · Java %.1f MB",
                up / 60, up % 60, cpuPct, pssMb, javaMb));
        perfWall = now;
        perfCpu = cpu;
    }

    @Override
    protected void onDestroy() {
        recordingTemplate = false;
        stopDetector();
        main.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private static class Template {
        final String phrase;
        final int samples;
        final double[][] features;
        Template(String phrase, int samples, double[][] features) {
            this.phrase = phrase;
            this.samples = samples;
            this.features = features;
        }
    }

    /** Minimal MFCC + DTW implementation, no third-party runtime. */
    private static class Mfcc {
        private static final int WIN = 400; // 25 ms
        private static final int HOP = 160; // 10 ms
        private static final int FFT_N = 512;
        private static final int MEL = 24;
        private static final int COEFF = 13;

        static short[] trim(short[] x) {
            if (x == null || x.length < FRAME) return x == null ? new short[0] : x;
            int frames = x.length / FRAME;
            double[] e = new double[frames];
            double max = 0;
            for (int f = 0; f < frames; f++) {
                double s = 0;
                int off = f * FRAME;
                for (int i = 0; i < FRAME; i++) {
                    double v = x[off + i];
                    s += v * v;
                }
                e[f] = Math.sqrt(s / FRAME);
                max = Math.max(max, e[f]);
            }
            if (max < 200) return new short[0];
            double th = Math.max(180, max * 0.13);
            int first = 0;
            while (first < frames && e[first] < th) first++;
            int last = frames - 1;
            while (last > first && e[last] < th) last--;
            first = Math.max(0, first - 5);
            last = Math.min(frames - 1, last + 6);
            int a = first * FRAME;
            int b = Math.min(x.length, (last + 1) * FRAME);
            return Arrays.copyOfRange(x, a, b);
        }

        static double[][] extract(short[] pcm) {
            pcm = trim(pcm);
            if (pcm.length < WIN) return new double[0][0];
            int count = 1 + (pcm.length - WIN) / HOP;
            double[][] out = new double[count][COEFF];
            int[] bins = melBins();
            double[] re = new double[FFT_N];
            double[] im = new double[FFT_N];

            for (int f = 0; f < count; f++) {
                Arrays.fill(re, 0);
                Arrays.fill(im, 0);
                int off = f * HOP;
                for (int i = 0; i < WIN; i++) {
                    double w = 0.54 - 0.46 * Math.cos(2.0 * Math.PI * i / (WIN - 1));
                    re[i] = (pcm[off + i] / 32768.0) * w;
                }
                fft(re, im);
                double[] power = new double[FFT_N / 2 + 1];
                for (int k = 0; k < power.length; k++) power[k] = re[k] * re[k] + im[k] * im[k];

                double[] logMel = new double[MEL];
                for (int m = 0; m < MEL; m++) {
                    int l = bins[m], c = bins[m + 1], r = bins[m + 2];
                    double sum = 0;
                    for (int k = l; k < c && k < power.length; k++) {
                        double den = Math.max(1, c - l);
                        sum += power[k] * (k - l) / den;
                    }
                    for (int k = c; k <= r && k < power.length; k++) {
                        double den = Math.max(1, r - c);
                        sum += power[k] * (r - k) / den;
                    }
                    logMel[m] = Math.log(sum + 1e-10);
                }

                for (int c = 0; c < COEFF; c++) {
                    double s = 0;
                    for (int m = 0; m < MEL; m++) {
                        s += logMel[m] * Math.cos(Math.PI * c * (m + 0.5) / MEL);
                    }
                    out[f][c] = s;
                }
            }

            // Cepstral mean/variance normalization makes matching less sensitive to mic gain.
            for (int c = 0; c < COEFF; c++) {
                double mean = 0;
                for (double[] row : out) mean += row[c];
                mean /= out.length;
                double var = 0;
                for (double[] row : out) {
                    double d = row[c] - mean;
                    var += d * d;
                }
                double sd = Math.sqrt(var / out.length + 1e-6);
                for (double[] row : out) row[c] = (row[c] - mean) / sd;
            }
            return out;
        }

        private static int[] melBins() {
            int[] b = new int[MEL + 2];
            double minMel = hzToMel(180);
            double maxMel = hzToMel(7800);
            for (int i = 0; i < b.length; i++) {
                double mel = minMel + (maxMel - minMel) * i / (b.length - 1.0);
                double hz = melToHz(mel);
                b[i] = Math.max(0, Math.min(FFT_N / 2, (int) Math.floor((FFT_N + 1) * hz / SAMPLE_RATE)));
            }
            return b;
        }

        private static double hzToMel(double hz) { return 2595.0 * Math.log10(1.0 + hz / 700.0); }
        private static double melToHz(double mel) { return 700.0 * (Math.pow(10.0, mel / 2595.0) - 1.0); }

        static double dtw(double[][] a, double[][] b) {
            int n = a.length, m = b.length;
            int band = Math.max(Math.abs(n - m) + 5, Math.max(8, Math.max(n, m) / 3));
            double inf = 1e18;
            double[] prev = new double[m + 1];
            double[] cur = new double[m + 1];
            Arrays.fill(prev, inf);
            prev[0] = 0;
            for (int i = 1; i <= n; i++) {
                Arrays.fill(cur, inf);
                int lo = Math.max(1, i - band);
                int hi = Math.min(m, i + band);
                for (int j = lo; j <= hi; j++) {
                    double cost = frameDistance(a[i - 1], b[j - 1]);
                    cur[j] = cost + Math.min(prev[j], Math.min(cur[j - 1], prev[j - 1]));
                }
                double[] t = prev; prev = cur; cur = t;
            }
            return prev[m] / Math.max(1, n + m);
        }

        private static double frameDistance(double[] x, double[] y) {
            double s = 0;
            for (int i = 0; i < Math.min(x.length, y.length); i++) {
                double d = x[i] - y[i];
                s += d * d;
            }
            return Math.sqrt(s);
        }

        private static void fft(double[] re, double[] im) {
            int n = re.length;
            for (int i = 1, j = 0; i < n; i++) {
                int bit = n >> 1;
                for (; (j & bit) != 0; bit >>= 1) j ^= bit;
                j ^= bit;
                if (i < j) {
                    double tr = re[i]; re[i] = re[j]; re[j] = tr;
                    double ti = im[i]; im[i] = im[j]; im[j] = ti;
                }
            }
            for (int len = 2; len <= n; len <<= 1) {
                double ang = -2 * Math.PI / len;
                double wlenR = Math.cos(ang), wlenI = Math.sin(ang);
                for (int i = 0; i < n; i += len) {
                    double wr = 1, wi = 0;
                    for (int j = 0; j < len / 2; j++) {
                        int u = i + j, v = i + j + len / 2;
                        double vr = re[v] * wr - im[v] * wi;
                        double vi = re[v] * wi + im[v] * wr;
                        re[v] = re[u] - vr;
                        im[v] = im[u] - vi;
                        re[u] += vr;
                        im[u] += vi;
                        double nwr = wr * wlenR - wi * wlenI;
                        wi = wr * wlenI + wi * wlenR;
                        wr = nwr;
                    }
                }
            }
        }
    }
}
