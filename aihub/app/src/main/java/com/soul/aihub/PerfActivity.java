package com.soul.aihub;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public class PerfActivity extends MainActivity {
    private final Handler perfHandler = new Handler(Looper.getMainLooper());
    private TextView perfText;
    private PerfMeter perfMeter;

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
        perfMeter = new PerfMeter();

        ViewGroup content = findViewById(android.R.id.content);
        if (content != null && content.getChildCount() > 0 && content.getChildAt(0) instanceof LinearLayout) {
            LinearLayout root = (LinearLayout) content.getChildAt(0);

            Button localWakeButton = new Button(this);
            localWakeButton.setAllCaps(false);
            localWakeButton.setTextSize(17);
            localWakeButton.setText("비교 테스트 · 로컬 옥자 감지");
            localWakeButton.setOnClickListener(v -> {
                startActivity(new Intent(this, StableTemplateWakeActivity.class));
                // Destroy STT activity so the local benchmark has no SpeechRecognizer/TTS overlap.
                finish();
            });
            LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT
            );
            buttonParams.topMargin = 20;
            root.addView(localWakeButton, buttonParams);

            perfText = new TextView(this);
            perfText.setTextColor(Color.rgb(160, 255, 180));
            perfText.setTextSize(13);
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
        if (perfText == null || perfMeter == null) return;
        perfText.setText(perfMeter.snapshot("STT WAKE"));
    }

    @Override
    protected void onDestroy() {
        perfHandler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
