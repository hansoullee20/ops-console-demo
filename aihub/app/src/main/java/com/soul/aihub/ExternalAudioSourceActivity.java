package com.soul.aihub;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.File;
import java.io.FileInputStream;
import java.io.OutputStream;

/** Diagnostic launcher for Mode F: one AudioRecord + ring buffer + EXTRA_AUDIO_SOURCE. */
public class ExternalAudioSourceActivity extends Activity {
    private static final int REQ_AUDIO = 3001;
    private static final int REQ_EXPORT = 3002;

    private TextView stateText;
    private TextView resultText;
    private ExternalAudioSourceTrial trial;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        DiagnosticTrace.init(this);
        DiagnosticTrace.setMode("F");
        buildUi();
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
        }
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(30, 36, 30, 30);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.rgb(16, 16, 18));

        root.addView(text("옥자 Fold4 진단 · Mode F", 27, Color.WHITE));
        root.addView(text("ONE AudioRecord → 2s ring buffer → SpeechRecognizer EXTRA_AUDIO_SOURCE", 14, Color.LTGRAY));

        stateText = text("IDLE", 20, Color.WHITE);
        resultText = text("START 후 ‘옥자야 뭐하니’를 한 번 자연스럽게 말하세요.", 16, Color.rgb(190, 220, 255));
        root.addView(stateText);
        root.addView(resultText);

        Button start = button("START MODE F");
        start.setOnClickListener(v -> startTrial());
        root.addView(start);

        Button beep = button("띠링 들림 · MARK");
        beep.setSoundEffectsEnabled(false);
        beep.setHapticFeedbackEnabled(false);
        beep.setOnClickListener(v -> {
            DiagnosticTrace.markBeep(stateText.getText().toString());
            resultText.setText("USER_BEEP_MARK 저장됨");
        });
        root.addView(beep);

        Button export = button("Export JSONL");
        export.setOnClickListener(v -> exportLog());
        root.addView(export);

        TextView note = text(
                "목표: 마이크를 놓지 않은 채 pre-roll+live PCM을 recognizer에 주었을 때 ‘옥자’가 보존되는지, 그리고 recognizer가 자체 마이크를 다시 여는지 확인합니다.",
                14, Color.LTGRAY);
        root.addView(note);
        setContentView(root);
    }

    private void startTrial() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
            return;
        }
        stopTrial();
        DiagnosticTrace.setMode("F");
        DiagnosticTrace.beginTrial();
        DiagnosticTrace.beginAttempt();
        resultText.setText("말하세요: ‘옥자야 뭐하니’");
        trial = new ExternalAudioSourceTrial(this, new ExternalAudioSourceTrial.Callback() {
            @Override public void onState(String state) {
                stateText.setText(state);
            }

            @Override public void onResult(String text) {
                resultText.setText(text);
            }
        });
        trial.start();
    }

    private void stopTrial() {
        if (trial != null) {
            trial.stop();
            trial = null;
        }
    }

    private Button button(String label) {
        Button b = new Button(this);
        b.setAllCaps(false);
        b.setText(label);
        b.setTextSize(17);
        return b;
    }

    private TextView text(String s, float sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setGravity(Gravity.CENTER);
        t.setPadding(6, 12, 6, 12);
        return t;
    }

    private void exportLog() {
        DiagnosticTrace.flush(1500);
        File f = DiagnosticTrace.currentFile();
        if (f == null || !f.exists()) {
            resultText.setText("No log file");
            return;
        }
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.setType("application/json");
        i.putExtra(Intent.EXTRA_TITLE, f.getName());
        startActivityForResult(i, REQ_EXPORT);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_EXPORT && resultCode == RESULT_OK && data != null && data.getData() != null) {
            DiagnosticTrace.flush(1500);
            File f = DiagnosticTrace.currentFile();
            try (FileInputStream in = new FileInputStream(f);
                 OutputStream out = getContentResolver().openOutputStream(data.getData())) {
                byte[] b = new byte[8192];
                int n;
                while ((n = in.read(b)) > 0) out.write(b, 0, n);
                resultText.setText("Export complete");
            } catch (Exception e) {
                resultText.setText("Export failed: " + e.getClass().getSimpleName());
            }
        }
    }

    @Override protected void onPause() {
        stopTrial();
        super.onPause();
    }

    @Override protected void onDestroy() {
        stopTrial();
        super.onDestroy();
    }
}
