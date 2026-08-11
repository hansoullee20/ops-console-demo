package com.soul.aihub;

import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public class StableTemplateWakeActivity extends TemplateWakeActivity {
    private final Handler stableHandler = new Handler(Looper.getMainLooper());
    private PerfMeter perfMeter;
    private TextView stablePerfText;

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (stablePerfText != null && perfMeter != null) {
                stablePerfText.setText(perfMeter.snapshot("LOCAL WAKE"));
            }
            stableHandler.postDelayed(this, 2000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        perfMeter = new PerfMeter();

        ViewGroup content = findViewById(android.R.id.content);
        if (content != null && content.getChildCount() > 0 && content.getChildAt(0) instanceof LinearLayout) {
            LinearLayout root = (LinearLayout) content.getChildAt(0);

            // Hide the old 2-second-only metric so there is one source of truth.
            for (int i = root.getChildCount() - 1; i >= 0; i--) {
                View v = root.getChildAt(i);
                if (v instanceof TextView) {
                    ((TextView) v).setVisibility(View.GONE);
                    break;
                }
            }

            Button sttButton = new Button(this);
            sttButton.setAllCaps(false);
            sttButton.setTextSize(16);
            sttButton.setText("비교 테스트 · STT 웨이크로 전환");
            sttButton.setOnClickListener(v -> {
                startActivity(new Intent(this, PerfActivity.class));
                finish();
            });
            LinearLayout.LayoutParams buttonParams = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT);
            buttonParams.topMargin = 18;
            root.addView(sttButton, buttonParams);

            stablePerfText = new TextView(this);
            stablePerfText.setTextColor(Color.rgb(160, 255, 180));
            stablePerfText.setTextSize(13);
            stablePerfText.setGravity(Gravity.CENTER);
            stablePerfText.setPadding(8, 18, 8, 8);
            root.addView(stablePerfText, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT));
        }

        if (stablePerfText != null) stablePerfText.setText(perfMeter.snapshot("LOCAL WAKE"));
        stableHandler.postDelayed(tick, 2000);
    }

    @Override
    protected void onDestroy() {
        stableHandler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }
}
