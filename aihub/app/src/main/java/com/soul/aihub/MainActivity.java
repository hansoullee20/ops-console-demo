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
import android.speech.tts.UtteranceProgressListener;
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
    private enum ListenMode { IDLE, WAKE, COMMAND }

    private Profile profile = Profile.PERSONAL;
    private String personalLanguage = "ko-KR";
    private ListenMode listenMode = ListenMode.IDLE;
    private boolean handsFree = true;
    private boolean destroyed = false;

    private TextView titleText;
    private TextView stateText;
    private TextView transcriptText;
    private TextView answerText;
    private Button profileButton;
    private Button languageButton;
    private Button handsFreeButton;
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
            resetListening();
            applyProfileUi();
            scheduleWakeListening(400);
        });

        languageButton = button();
        languageButton.setOnClickListener(v -> {
            if (profile == Profile.PERSONAL) {
                personalLanguage = personalLanguage.equals("ko-KR") ? "en-US" : "ko-KR";
                resetListening();
                applyProfileUi();
                scheduleWakeListening(400);
            }
        });

        handsFreeButton = button();
        handsFreeButton.setOnClickListener(v -> {
            handsFree = !handsFree;
            if (handsFree) {
                handsFreeButton.setText("웨이크워드: 켜짐");
                scheduleWakeListening(200);
            } else {
                handsFreeButton.setText("웨이크워드: 꺼짐");
                resetListening();
                stateText.setText("버튼 모드");
            }
        });

        talkButton = button();
        talkButton.setText("지금 말하기");
        talkButton.setTextSize(20);
        talkButton.setOnClickListener(v -> startCommandListening());

        root.addView(titleText, fullWidth());
        root.addView(space(14));
        root.addView(stateText, fullWidth());
        root.addView(space(28));
        root.addView(profileButton, fullWidth());
        root.addView(space(10));
        root.addView(languageButton, fullWidth());
        root.addView(space(10));
        root.addView(handsFreeButton, fullWidth());
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
            transcriptText.setText("'옥자'라고 부르면 듣습니다.");
        } else {
            titleText.setText("AI Hub");
            profileButton.setText("Profile: Personal");
            languageButton.setEnabled(true);
            languageButton.setText(personalLanguage.equals("ko-KR") ? "입력 언어: 한국어" : "Input language: English");
            transcriptText.setText(personalLanguage.equals("ko-KR")
                    ? "'에이아이 허브'라고 부르면 듣습니다."
                    : "Say 'AI Hub' to wake me.");
        }
        handsFreeButton.setText(handsFree ? "웨이크워드: 켜짐" : "웨이크워드: 꺼짐");
        answerText.setText("");
        if (recognizer != null && handsFree) {
            stateText.setText(wakePrompt());
        } else {
            stateText.setText("준비됨 · " + recognitionLanguage());
        }
    }

    private String wakePrompt() {
        if (profile == Profile.GRANDMA) return "대기 중 · '옥자'";
        return personalLanguage.equals("en-US") ? "Waiting · 'AI Hub'" : "대기 중 · '에이아이 허브'";
    }

    private String recognitionLanguage() {
        return profile == Profile.GRANDMA ? "ko-KR" : personalLanguage;
    }

    private void initSpeech() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            stateText.setText("이 기기에서 음성인식을 사용할 수 없음");
            talkButton.setEnabled(false);
            handsFreeButton.setEnabled(false);
            return;
        }

        recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        recognizer.setRecognitionListener(new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle params) {
                stateText.setText(listenMode == ListenMode.WAKE ? wakePrompt() : "듣고 있습니다…");
            }

            @Override public void onBeginningOfSpeech() {
                if (listenMode == ListenMode.COMMAND) stateText.setText("말씀하세요");
            }

            @Override public void onRmsChanged(float rmsdB) {}
            @Override public void onBufferReceived(byte[] buffer) {}

            @Override public void onEndOfSpeech() {
                if (listenMode == ListenMode.COMMAND) stateText.setText("인식 중…");
            }

            @Override public void onError(int error) {
                ListenMode failedMode = listenMode;
                listenMode = ListenMode.IDLE;
                talkButton.setEnabled(true);

                if (handsFree && failedMode == ListenMode.WAKE) {
                    scheduleWakeListening(350);
                } else if (handsFree && failedMode == ListenMode.COMMAND) {
                    stateText.setText("다시 대기합니다");
                    scheduleWakeListening(650);
                } else {
                    stateText.setText("음성인식 오류: " + error);
                }
            }

            @Override public void onResults(Bundle results) {
                ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                ListenMode completedMode = listenMode;
                listenMode = ListenMode.IDLE;

                if (matches == null || matches.isEmpty()) {
                    talkButton.setEnabled(true);
                    if (handsFree) scheduleWakeListening(350);
                    return;
                }

                String spoken = matches.get(0).trim();

                if (completedMode == ListenMode.WAKE) {
                    if (containsWakePhrase(matches)) {
                        transcriptText.setText(profile == Profile.GRANDMA ? "네, 말씀하세요." : "Listening…");
                        stateText.setText("깨움 감지");
                        main.postDelayed(() -> startCommandListening(), 250);
                    } else if (handsFree) {
                        scheduleWakeListening(250);
                    }
                    return;
                }

                if (completedMode == ListenMode.COMMAND) {
                    transcriptText.setText((profile == Profile.GRANDMA ? "할머니: " : "You: ") + spoken);
                    stateText.setText("Claude에게 보내는 중…");
                    sendToBridge(spoken);
                }
            }

            @Override public void onPartialResults(Bundle partialResults) {
                if (listenMode != ListenMode.COMMAND) return;
                ArrayList<String> matches = partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                if (matches != null && !matches.isEmpty()) transcriptText.setText(matches.get(0));
            }

            @Override public void onEvent(int eventType, Bundle params) {}
        });

        talkButton.setEnabled(true);
        applyProfileUi();
        scheduleWakeListening(700);
    }

    private boolean containsWakePhrase(ArrayList<String> matches) {
        for (String candidate : matches) {
            String normalized = candidate.toLowerCase(Locale.ROOT)
                    .replace(" ", "")
                    .replace("-", "");

            if (profile == Profile.GRANDMA) {
                if (normalized.contains("옥자")) return true;
            } else {
                if (normalized.contains("aihub") ||
                        normalized.contains("에이아이허브") ||
                        normalized.contains("에이아이합") ||
                        normalized.contains("에이아이하브")) return true;
            }
        }
        return false;
    }

    private Intent recognizerIntent(String lang, boolean partial) {
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, lang);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, lang);
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, partial);
        i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5);
        return i;
    }

    private void scheduleWakeListening(long delayMs) {
        if (!handsFree || recognizer == null || destroyed) return;
        main.postDelayed(() -> {
            if (handsFree && listenMode == ListenMode.IDLE && !destroyed) startWakeListening();
        }, delayMs);
    }

    private void startWakeListening() {
        if (!handsFree || recognizer == null || destroyed) return;
        try {
            recognizer.cancel();
            listenMode = ListenMode.WAKE;
            stateText.setText(wakePrompt());
            recognizer.startListening(recognizerIntent(recognitionLanguage(), false));
        } catch (Exception e) {
            listenMode = ListenMode.IDLE;
            scheduleWakeListening(750);
        }
    }

    private void startCommandListening() {
        if (recognizer == null || destroyed) {
            initSpeech();
            if (recognizer == null) return;
        }

        try {
            recognizer.cancel();
            listenMode = ListenMode.COMMAND;
            talkButton.setEnabled(false);
            answerText.setText("");
            stateText.setText("듣고 있습니다…");
            recognizer.startListening(recognizerIntent(recognitionLanguage(), true));
        } catch (Exception e) {
            listenMode = ListenMode.IDLE;
            talkButton.setEnabled(true);
            stateText.setText("음성인식 시작 실패");
            if (handsFree) scheduleWakeListening(700);
        }
    }

    private void resetListening() {
        listenMode = ListenMode.IDLE;
        if (recognizer != null) {
            try { recognizer.cancel(); } catch (Exception ignored) {}
        }
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
                stateText.setText("답변 중…");
                talkButton.setEnabled(true);
                speak(reply, lang);
            });
        });
    }

    private void initTts() {
        tts = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                tts.setSpeechRate(1.02f);
                tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    @Override public void onStart(String utteranceId) {
                        main.post(() -> {
                            resetListening();
                            stateText.setText("답변 중…");
                        });
                    }

                    @Override public void onDone(String utteranceId) {
                        main.post(() -> {
                            listenMode = ListenMode.IDLE;
                            stateText.setText(handsFree ? wakePrompt() : "준비됨");
                            if (handsFree) scheduleWakeListening(650);
                        });
                    }

                    @Override public void onError(String utteranceId) {
                        main.post(() -> {
                            listenMode = ListenMode.IDLE;
                            if (handsFree) scheduleWakeListening(650);
                        });
                    }
                });
            }
        });
    }

    private void speak(String text, String lang) {
        if (tts == null) {
            if (handsFree) scheduleWakeListening(500);
            return;
        }
        resetListening();
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
        destroyed = true;
        main.removeCallbacksAndMessages(null);
        if (recognizer != null) recognizer.destroy();
        if (tts != null) {
            tts.stop();
            tts.shutdown();
        }
        ioPool.shutdownNow();
        super.onDestroy();
    }
}
