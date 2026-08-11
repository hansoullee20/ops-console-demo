package com.soul.aihub;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Debug;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.Locale;

public class PerfActivity extends MainActivity {
    private final Handler perfHandler = new Handler(Looper.getMainLooper());
    private TextView perfText;
    private long startedWallMs;
    private long lastWallMs;
    private long lastCpuMs;

    private final Runnable perfTick = new Runnable() {
        @Override
        public void run() {
            updatePerf();
            perfHandler.postDelayed(this, 2000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        startedWallMs = SystemClock.elapsedRealtime();
        lastWallMs = startedWallMs;
        lastCpuMs = Process.getElapsedCpuTime();

        ViewGroup content = findViewById(android.R.id.content);
        if (content != null && content.getChildCount() > 0 && content.getChildAt(0) instanceof LinearLayout) {
            LinearLayout root = (LinearLayout) content.getChildAt(0);

            Button localWakeButton = new Button(this);
            localWakeButton.setAllCaps(false);
            localWakeButton.setTextSize(17);
            localWakeButton.setText("실험 · 초경량 로컬 옥자 감지");
            localWakeButton.setOnClickListener(v ->
                    startActivity(new Intent(this, TemplateWakeActivity.class)));
            LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
            );
            buttonParams.topMargin = 20;
            root.addView(localWakeButton, buttonParams);

            perfText = new TextView(this);
            perfText.setTextColor(Color.rgb(160, 255, 180));
            perfText.setTextSize(14);
            perfText.setGravity(Gravity.CENTER);
            perfText.setPadding(8, 22, 8, 8);
            root.addView(perfText, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
            ));
        }

        updatePerf();
        perfHandler.postDelayed(perfTick, 2000);
    }

    private void updatePerf() {
        if (perfText == null) return;

        long nowWall = SystemClock.elapsedRealtime();
        long nowCpu = Process.getElapsedCpuTime();
        long wallDelta = Math.max(1, nowWall - lastWallMs);
        long cpuDelta = Math.max(0, nowCpu - lastCpuMs);
        double cpuPct = (cpuDelta * 100.0) / wallDelta;

        long pssKb = Debug.getPss();
        Runtime rt = Runtime.getRuntime();
        long javaUsedBytes = rt.totalMemory() - rt.freeMemory();
        double javaMb = javaUsedBytes / (1024.0 * 1024.0);
        double pssMb = pssKb / 1024.0;
        long uptimeSec = (nowWall - startedWallMs) / 1000;

        perfText.setText(String.format(Locale.US,
                "PERF · uptime %02d:%02d · app CPU %.1f%% · PSS %.1f MB · Java %.1f MB",
                uptimeSec / 60,
                uptimeSec % 60,
                cpuPct,
                pssMb,
                javaMb));

        lastWallMs = nowWall;
        lastCpuMs = nowCpu;
    }

    @Override
    protected void onDestroy() {
        perfHandler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
