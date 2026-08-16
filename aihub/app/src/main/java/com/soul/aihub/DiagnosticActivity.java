package com.soul.aihub;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.OutputStream;
import java.util.ArrayList;

public class DiagnosticActivity extends Activity {
    private static final int REQ_AUDIO = 2001;
    private static final int REQ_EXPORT = 2002;

    private enum Mode { A, B1, B2, C, D, E }
    private Mode mode = Mode.A;
    private TextView stateText, modeText, resultText;
    private Button startButton, eButton;
    private QuietWakeGate gate;
    private SpeechRecognizer recognizer;
    private String state = "IDLE";

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        DiagnosticTrace.init(this);
        buildUi();
        selectMode(Mode.A);
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
        }
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(30, 32, 30, 30);
        root.setBackgroundColor(Color.rgb(16,16,18));

        TextView title = text("옥자 Fold4 진단", 28, Color.WHITE);
        modeText = text("", 17, Color.rgb(180,220,255));
        stateText = text("IDLE", 19, Color.WHITE);
        resultText = text("동일 문구: ‘옥자 뭐하니’", 15, Color.LTGRAY);
        root.addView(title); root.addView(modeText); root.addView(stateText); root.addView(resultText);

        LinearLayout modes = new LinearLayout(this); modes.setOrientation(LinearLayout.VERTICAL);
        addModeButton(modes, "A · Gate only", Mode.A);
        addModeButton(modes, "B1 · SR one-shot / no cancel", Mode.B1);
        addModeButton(modes, "B2 · SR one-shot / cancel→start", Mode.B2);
        addModeButton(modes, "C · Gate→SR one-shot / no rearm", Mode.C);
        addModeButton(modes, "D · Production loop control", Mode.D);
        eButton = addModeButton(modes, "E · On-device SR one-shot", Mode.E);
        eButton.setEnabled(android.os.Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(this));
        root.addView(modes);

        startButton = button("START TRIAL");
        startButton.setOnClickListener(v -> startTrial());
        root.addView(startButton);

        Button beep = button("띠링 들림 · MARK");
        beep.setOnClickListener(v -> { DiagnosticTrace.markBeep(state); resultText.setText("USER_BEEP_MARK 저장됨"); });
        root.addView(beep);

        Button export = button("Export JSONL");
        export.setOnClickListener(v -> exportLog());
        root.addView(export);
        setContentView(root);
    }

    private Button addModeButton(LinearLayout parent, String label, Mode m) {
        Button b = button(label); b.setOnClickListener(v -> selectMode(m)); parent.addView(b); return b;
    }
    private Button button(String label) { Button b = new Button(this); b.setAllCaps(false); b.setText(label); b.setTextSize(16); return b; }
    private TextView text(String s, float sp, int color) { TextView t = new TextView(this); t.setText(s); t.setTextSize(sp); t.setTextColor(color); t.setGravity(Gravity.CENTER); t.setPadding(6,10,6,10); return t; }

    private void selectMode(Mode m) {
        stopAll(); mode = m; DiagnosticTrace.setMode(m.name());
        modeText.setText("Mode " + m.name()); state = "IDLE"; stateText.setText(state);
        resultText.setText(m == Mode.D ? "START 후 production control 화면으로 이동" : "동일 문구: ‘옥자 뭐하니’");
    }

    private void startTrial() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO); return;
        }
        stopAll(); DiagnosticTrace.beginTrial(); DiagnosticTrace.beginAttempt();
        resultText.setText("Trial running…");
        if (mode == Mode.A) startGateOnly();
        else if (mode == Mode.B1) startRecognizer(false, false);
        else if (mode == Mode.B2) startRecognizer(true, false);
        else if (mode == Mode.C) startGateThenRecognizer();
        else if (mode == Mode.D) {
            DiagnosticTrace.setMode("D");
            Intent i = new Intent(this, PerfActivity.class); i.putExtra("okja_diag_mode", "D"); startActivity(i);
        } else if (mode == Mode.E) startRecognizer(false, true);
    }

    private QuietWakeGate newGate(QuietWakeGate.Callback callback) { return new QuietWakeGate(callback); }

    private void startGateOnly() {
        state = "GATE_WAIT"; stateText.setText(state);
        gate = newGate(new QuietWakeGate.Callback() {
            @Override public void onSpeechActivity() { state="GATE_ONSET_STOP"; stateText.setText(state); resultText.setText("A complete · onset captured · no SR started"); }
            @Override public void onFailure(String reason) { state="GATE_ERROR"; stateText.setText(state); resultText.setText(reason); }
        });
        gate.start();
    }

    private void startGateThenRecognizer() {
        state = "GATE_WAIT"; stateText.setText(state);
        gate = newGate(new QuietWakeGate.Callback() {
            @Override public void onSpeechActivity() {
                state="HANDOFF_TO_SR"; stateText.setText(state);
                startRecognizer(false, false);
            }
            @Override public void onFailure(String reason) { state="GATE_ERROR"; stateText.setText(state); resultText.setText(reason); }
        });
        gate.start();
    }

    private void startRecognizer(boolean cancelFirst, boolean onDevice) {
        destroyRecognizer();
        try {
            recognizer = onDevice && android.os.Build.VERSION.SDK_INT >= 31
                    ? SpeechRecognizer.createOnDeviceSpeechRecognizer(this)
                    : SpeechRecognizer.createSpeechRecognizer(this);
            recognizer.setRecognitionListener(listener());
            logRecognizerIdentity(onDevice);
            if (cancelFirst) {
                DiagnosticTrace.log("SR_CANCEL_REQUESTED", null);
                recognizer.cancel();
                DiagnosticTrace.log("SR_CANCEL_RETURNED", null);
            }
            DiagnosticTrace.nextGeneration();
            DiagnosticTrace.log("SR_START_REQUESTED", null);
            state="SR_START_REQUESTED"; stateText.setText(state);
            recognizer.startListening(recognizerIntent(true));
            DiagnosticTrace.log("SR_START_RETURNED", null);
        } catch (Exception e) {
            JSONObject p=new JSONObject(); try { p.put("error", e.getClass().getSimpleName()); p.put("message", String.valueOf(e.getMessage())); } catch(Exception ignored){}
            DiagnosticTrace.log("SR_START_EXCEPTION", p); state="SR_START_EXCEPTION"; stateText.setText(state); resultText.setText(e.toString());
        }
    }

    private RecognitionListener listener() {
        return new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle params) { state="SR_ON_READY"; stateText.setText(state); DiagnosticTrace.log("SR_ON_READY", null); }
            @Override public void onBeginningOfSpeech() { state="SR_BEGIN_SPEECH"; stateText.setText(state); DiagnosticTrace.log("SR_BEGIN_SPEECH", null); }
            @Override public void onRmsChanged(float rmsdB) {}
            @Override public void onBufferReceived(byte[] buffer) {}
            @Override public void onEndOfSpeech() { state="SR_END_SPEECH"; stateText.setText(state); DiagnosticTrace.log("SR_END_SPEECH", null); }
            @Override public void onError(int error) { JSONObject p=new JSONObject(); try{p.put("error_code",error);}catch(Exception ignored){} DiagnosticTrace.log("SR_ERROR",p); state="SR_ERROR_"+error; stateText.setText(state); resultText.setText("SR error " + error + " · STOP (no rearm)"); destroyRecognizer(); }
            @Override public void onResults(Bundle results) {
                ArrayList<String> m = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                DiagnosticTrace.logCandidates("SR_RESULTS", m);
                boolean wake = containsWake(m);
                JSONObject p=new JSONObject(); try { p.put("wake_present", wake); } catch(Exception ignored){}
                DiagnosticTrace.log(wake?"WAKE_ACCEPT":"WAKE_REJECT",p);
                state = wake?"WAKE_ACCEPT":"WAKE_REJECT"; stateText.setText(state);
                resultText.setText(m==null?"[]":m.toString());
                destroyRecognizer();
            }
            @Override public void onPartialResults(Bundle partialResults) { ArrayList<String> m=partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION); DiagnosticTrace.logCandidates("SR_PARTIAL",m); }
            @Override public void onEvent(int eventType, Bundle params) { JSONObject p=new JSONObject(); try{p.put("event_type",eventType);}catch(Exception ignored){} DiagnosticTrace.log("SR_EVENT",p); }
        };
    }

    private boolean containsWake(ArrayList<String> m) {
        if (m == null) return false;
        for(String s:m){String n=s.toLowerCase(java.util.Locale.ROOT).replace(" ","").replace("-",""); if(n.contains("옥자")||n.contains("옥짜")||n.contains("okja")||n.contains("heyokja")||n.contains("okayokja")) return true;}
        return false;
    }

    private Intent recognizerIntent(boolean partial) {
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "ko-KR");
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "ko-KR");
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, partial);
        i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5);
        return i;
    }

    private void logRecognizerIdentity(boolean onDevice) {
        JSONObject p=new JSONObject();
        try {
            p.put("on_device", onDevice);
            p.put("on_device_available", android.os.Build.VERSION.SDK_INT >= 31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(this));
            p.put("voice_recognition_service", android.provider.Settings.Secure.getString(getContentResolver(), "voice_recognition_service"));
        } catch(Exception ignored){}
        DiagnosticTrace.log("SR_IMPLEMENTATION",p);
    }

    private void stopAll() { if(gate!=null){gate.stop();gate=null;} destroyRecognizer(); }
    private void destroyRecognizer() { if(recognizer!=null){ try{DiagnosticTrace.log("SR_DESTROYED",null);recognizer.destroy();}catch(Exception ignored){} recognizer=null; } }

    private void exportLog() {
        File f=DiagnosticTrace.currentFile(); if(f==null||!f.exists()){resultText.setText("No log file");return;}
        Intent i=new Intent(Intent.ACTION_CREATE_DOCUMENT); i.setType("application/json"); i.putExtra(Intent.EXTRA_TITLE,f.getName()); startActivityForResult(i,REQ_EXPORT);
    }

    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){
        super.onActivityResult(requestCode,resultCode,data);
        if(requestCode==REQ_EXPORT&&resultCode==RESULT_OK&&data!=null&&data.getData()!=null){
            File f=DiagnosticTrace.currentFile();
            try(FileInputStream in=new FileInputStream(f); OutputStream out=getContentResolver().openOutputStream(data.getData())){
                byte[] b=new byte[8192]; int n; while((n=in.read(b))>0)out.write(b,0,n); resultText.setText("Export complete");
            }catch(Exception e){resultText.setText("Export failed: "+e.getClass().getSimpleName());}
        }
    }

    @Override protected void onPause(){ stopAll(); super.onPause(); }
    @Override protected void onDestroy(){ stopAll(); super.onDestroy(); }
}
