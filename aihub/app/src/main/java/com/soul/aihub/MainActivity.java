package com.soul.aihub;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int REQ_AUDIO = 1001;
    private static final int PORT = 8765;

    private enum Profile { GRANDMA, PERSONAL }

    private Profile profile = Profile.PERSONAL;
    private String personalLanguage = "ko-KR";

    private TextView titleText;
    private TextView stateText;
    private TextView transcriptText;
    private TextView answerText;
    private Button profileButton;
    private Button languageButton;
    private Button talkButton;

    private SpeechRecognizer recognizer;
    private TextToSpeech tts;
    private final ExecutorService ioPool = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        initTts();
        applyProfileUi();

        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
        } else {
            initSpeech();
        }
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(42, 52, 42, 42);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.rgb(18, 18, 20));

        titleText = text("AI Hub", 30, Color.WHITE);
        stateText = text("준비 중", 17, Color.LTGRAY);
        transcriptText = text("말해보세요.", 23, Color.WHITE);
        answerText = text("", 20, Color.rgb(190, 220, 255));

        profileButton = button();
        profileButton.setOnClickListener(v -> {
            profile = profile == Profile.PERSONAL ? Profile.GRANDMA : Profile.PERSONAL;
            applyProfileUi();
        });

        languageButton = button();
        languageButton.setOnClickListener(v -> {
            if (profile == Profile.PERSONAL) {
                personalLanguage = personalLanguage.equals("ko-KR") ? "en-US" : "ko-KR";
                applyProfileUi();
            }
        });

        talkButton = button();
        talkButton.setText("말하기");
        talkButton.setTextSize(21);
        talkButton.setOnClickListener(v -> startListening());

        root.addView(titleText, fullWidth());
        root.addView(space(14));
        root.addView(stateText, fullWidth());
        root.addView(space(28));
        root.addView(profileButton, fullWidth());
        root.addView(space(10));
        root.addView(languageButton, fullWidth());
        root.addView(space(26));
        root.addView(transcriptText, fullWidth());
        root.addView(space(20));
        root.addView(talkButton, fullWidth());
        root.addView(space(30));
        root.addView(answerText, fullWidth());

        setContentView(root);
    }

    private Button button() {
        Button b = new Button(this);
        b.setAllCaps(false);
        b.setTextSize(18);
        return b;
    }

    private TextView text(String s, float sp, int color) {
        TextView v = new TextView(this);
        v.setText(s);
        v.setTextSize(sp);
        v.setTextColor(color);
        v.setGravity(Gravity.CENTER);
        v.setPadding(8, 8, 8, 8);
        return v;
    }

    private View space(int h) {
        View v = new View(this);
        v.setLayoutParams(new LinearLayout.LayoutParams(1, h));
        return v;
    }

    private LinearLayout.LayoutParams fullWidth() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
    }

    private void applyProfileUi() {
        if (profile == Profile.GRANDMA) {
            titleText.setText("옥자");
            profileButton.setText("프로필: 할머니용");
            languageButton.setText("음성: 한국어 고정");
            languageButton.setEnabled(false);
            transcriptText.setText("옥자에게 한국어로 말씀하세요.");
        } else {
            titleText.setText("AI Hub");
            profileButton.setText("Profile: Personal");
            languageButton.setEnabled(true);
            languageButton.setText(personalLanguage.equals("ko-KR") ? "입력 언어: 한국어" : "Input language: English");
            transcriptText.setText(personalLanguage.equals("ko-KR") ? "한국어로 말해보세요." : "Speak in English.");
        }
        answerText.setText("");
        stateText.setText("준비됨 · " + recognitionLanguage());
    }

    private String recognitionLanguage() {
        return profile == Profile.GRANDMA ? "ko-KR" : personalLanguage;
    }

    private void initSpeech() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            stateText.setText("이 기기에서 음성인식을 사용할 수 없음");
            talkButton.setEnabled(false);
            return;
        }

        recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        recognizer.setRecognitionListener(new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle params) { stateText.setText("듣고 있습니다…"); }
            @Override public void onBeginningOfSpeech() { stateText.setText("말씀하세요"); }
            @Override public void onRmsChanged(float rmsdB) {}
            @Override public void onBufferReceived(byte[] buffer) {}
            @Override public void onEndOfSpeech() { stateText.setText("인식 중…"); }

            @Override public void onError(int error) {
                stateText.setText("음성인식 오류: " + error);
                talkButton.setEnabled(true);
            }

            @Override public void onResults(Bundle results) {
                ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                if (matches == null || matches.isEmpty()) {
                    stateText.setText("인식 결과 없음");
                    talkButton.setEnabled(true);
                    return;
                }
                String spoken = matches.get(0);
                transcriptText.setText((profile == Profile.GRANDMA ? "할머니: " : "You: ") + spoken);
                stateText.setText("Claude에게 보내는 중…");
                sendToBridge(spoken);
            }

            @Override public void onPartialResults(Bundle partialResults) {
                ArrayList<String> matches = partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                if (matches != null && !matches.isEmpty()) transcriptText.setText(matches.get(0));
            }

            @Override public void onEvent(int eventType, Bundle params) {}
        });
        talkButton.setEnabled(true);
        applyProfileUi();
    }

    private void startListening() {
        if (recognizer == null) {
            initSpeech();
            if (recognizer == null) return;
        }

        talkButton.setEnabled(false);
        answerText.setText("");
        String lang = recognitionLanguage();

        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, lang);
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5);
        recognizer.startListening(i);
    }

    private void sendToBridge(String prompt) {
        final String lang = recognitionLanguage();
        final String profileName = profile == Profile.GRANDMA ? "grandma" : "personal";

        ioPool.execute(() -> {
            String result;
            try (Socket socket = new Socket()) {
                socket.connect(new InetSocketAddress("127.0.0.1", PORT), 3000);
                socket.setSoTimeout(90000);

                JSONObject payload = new JSONObject();
                payload.put("profile", profileName);
                payload.put("language", lang);
                payload.put("text", prompt);

                byte[] out = payload.toString().getBytes(StandardCharsets.UTF_8);
                DataOutputStream dos = new DataOutputStream(socket.getOutputStream());
                DataInputStream dis = new DataInputStream(socket.getInputStream());
                dos.writeInt(out.length);
                dos.write(out);
                dos.flush();

                int len = dis.readInt();
                if (len < 0 || len > 2_000_000) throw new IllegalStateException("Bad reply length");
                byte[] in = new byte[len];
                dis.readFully(in);
                result = new String(in, StandardCharsets.UTF_8);
            } catch (Exception e) {
                result = "브리지 연결 실패: " + e.getClass().getSimpleName() + " - " + e.getMessage();
            }

            final String reply = result;
            main.post(() -> {
                answerText.setText(reply);
                stateText.setText("준비됨");
                talkButton.setEnabled(true);
                speak(reply, lang);
            });
        });
    }

    private void initTts() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) tts.setSpeechRate(1.02f);
        });
    }

    private void speak(String text, String lang) {
        if (tts == null) return;
        tts.setLanguage(lang.equals("en-US") ? Locale.US : Locale.KOREA);
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "aihub-reply");
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_AUDIO && grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            initSpeech();
        } else {
            stateText.setText("마이크 권한 필요");
        }
    }

    @Override
    protected void onDestroy() {
        if (recognizer != null) recognizer.destroy();
        if (tts != null) {
            tts.stop();
            tts.shutdown();
        }
        ioPool.shutdownNow();
        super.onDestroy();
    }
}
