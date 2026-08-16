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
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int REQ_AUDIO = 1001;
    private static final int PORT = 8765;
    private enum Profile { GRANDMA, PERSONAL }
    private enum ListenMode { IDLE, WAKE, COMMAND, FOLLOW_UP }

    private Profile profile = Profile.PERSONAL;
    private String personalLanguage = "ko-KR";
    private ListenMode listenMode = ListenMode.IDLE;
    private boolean handsFree = true;
    private boolean destroyed = false;
    private boolean bridgeDegraded = false;
    private boolean conversationActive = false;
    private int followUpNoMatchRetries = 0;
    private int interactionEpoch = 0;
    private boolean foreground = true;
    private boolean ttsReady = false;
    private static final int MAX_BRIDGE_PACKET_BYTES = 262144;
    private VoiceUiState.State uiState = VoiceUiState.State.READY;
    private String deviceId;
    private String sessionId;
    private String correlationId = "";
    private String lifecycleEventId;
    private String listeningEventId;

    private TextView titleText, stateText, transcriptText, answerText;
    private Button profileButton, languageButton, handsFreeButton, talkButton;
    private SpeechRecognizer recognizer;
    private QuietWakeGate quietWakeGate;
    private TextToSpeech tts;
    private final VoiceEventLedger eventLedger = new VoiceEventLedger(128);
    private final ExecutorService ioPool = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        DiagnosticTrace.init(this);
        if ("D".equals(getIntent().getStringExtra("okja_diag_mode"))) { DiagnosticTrace.setMode("D"); DiagnosticTrace.beginTrial(); }
        deviceId = getSharedPreferences("okja_identity", MODE_PRIVATE).getString("device_id", "");
        if (deviceId == null || deviceId.isEmpty()) {
            deviceId = "device-" + UUID.randomUUID();
            getSharedPreferences("okja_identity", MODE_PRIVATE).edit().putString("device_id", deviceId).apply();
        }
        sessionId = "session-" + UUID.randomUUID();
        buildUi(); initTts(); applyProfileUi();
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_AUDIO);
        } else initSpeech();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(42,52,42,42); root.setGravity(Gravity.CENTER_HORIZONTAL); root.setBackgroundColor(Color.rgb(18,18,20));
        titleText=text("옥자",30,Color.WHITE); stateText=text("준비 중",17,Color.LTGRAY);
        transcriptText=text("말해보세요.",23,Color.WHITE); answerText=text("",20,Color.rgb(190,220,255));
        profileButton=button(); profileButton.setOnClickListener(v->{ profile=profile==Profile.PERSONAL?Profile.GRANDMA:Profile.PERSONAL; endConversation(false); applyProfileUi(); scheduleWakeListening(400); });
        languageButton=button(); languageButton.setOnClickListener(v->{ if(profile==Profile.PERSONAL){ personalLanguage=personalLanguage.equals("ko-KR")?"en-US":"ko-KR"; endConversation(false); applyProfileUi(); scheduleWakeListening(400); }});
        handsFreeButton=button(); handsFreeButton.setOnClickListener(v->{ if(uiState==VoiceUiState.State.MIC_OFF)enableMicrophone();else disableMicrophone(); });
        talkButton=button(); talkButton.setText("지금 말하기"); talkButton.setTextSize(20); talkButton.setOnClickListener(v->startCommandListening(false));
        for(View v:new View[]{titleText,space(14),stateText,space(28),profileButton,space(10),languageButton,space(10),handsFreeButton,space(26),transcriptText,space(20),talkButton,space(30),answerText}) root.addView(v, v.getLayoutParams()!=null?v.getLayoutParams():fullWidth());
        setContentView(root);
    }
    private Button button(){Button b=new Button(this);b.setAllCaps(false);b.setTextSize(18);return b;}
    private TextView text(String s,float sp,int color){TextView v=new TextView(this);v.setText(s);v.setTextSize(sp);v.setTextColor(color);v.setGravity(Gravity.CENTER);v.setPadding(8,8,8,8);return v;}
    private View space(int h){View v=new View(this);v.setLayoutParams(new LinearLayout.LayoutParams(1,h));return v;}
    private LinearLayout.LayoutParams fullWidth(){return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,LinearLayout.LayoutParams.WRAP_CONTENT);}

    private void applyProfileUi(){
        titleText.setText("옥자");
        if(profile==Profile.GRANDMA){profileButton.setText("프로필: 할머니용");languageButton.setText("음성: 한국어 고정");languageButton.setEnabled(false);transcriptText.setText("'옥자' 또는 '옥자야'라고 부르면 듣습니다.");}
        else{profileButton.setText("Profile: Personal");languageButton.setEnabled(true);languageButton.setText(personalLanguage.equals("ko-KR")?"입력 언어: 한국어":"Input language: English");transcriptText.setText(personalLanguage.equals("ko-KR")?"'옥자' 또는 '옥자야'라고 부르면 듣습니다.":"Say 'Okja' or 'Hey Okja' to wake me.");}
        answerText.setText("");
        if(uiState==VoiceUiState.State.MIC_OFF){renderMicOff();return;}
        handsFreeButton.setText("마이크: 켜짐");
        talkButton.setEnabled(recognizer!=null&&VoiceUiState.manualTalkEnabled(uiState));
        stateText.setText(bridgeDegraded?offlinePrompt():(recognizer!=null?wakePrompt():"준비됨 · "+recognitionLanguage()));
    }
    private String wakePrompt(){return recognitionLanguage().equals("en-US")?"Waiting · 'Okja / Hey Okja'":"대기 중 · '옥자 / 옥자야'";}
    private String followUpPrompt(){return recognitionLanguage().equals("en-US")?"Listening for a follow-up…":"계속 말씀하세요…";}
    private String offlinePrompt(){return recognitionLanguage().equals("en-US")?"AI bridge unavailable · voice input can retry":"AI 브리지 연결 안 됨 · 음성 입력은 다시 시도 가능";}
    private String recognitionLanguage(){return profile==Profile.GRANDMA?"ko-KR":personalLanguage;}

    private void renderMicOff(){
        uiState=VoiceUiState.State.MIC_OFF;
        handsFreeButton.setText("마이크: 꺼짐");
        talkButton.setEnabled(false);
        stateText.setText(recognitionLanguage().equals("en-US")?"MIC OFF · no voice input":"마이크 꺼짐 · 음성 입력 없음");
        transcriptText.setText(recognitionLanguage().equals("en-US")?"Microphone access is stopped.":"음성 입력이 중지되었습니다.");
    }

    private void disableMicrophone(){
        handsFree=false;
        stopQuietWakeGate();
        endConversation(false);
        if(recognizer!=null){try{DiagnosticTrace.log("SR_DESTROYED",null);recognizer.destroy();}catch(Exception ignored){}recognizer=null;}
        renderMicOff();
    }

    private void enableMicrophone(){
        handsFree=true;
        bridgeDegraded=false;
        conversationActive=false;
        uiState=VoiceUiState.State.READY;
        handsFreeButton.setText("마이크: 켜짐");
        if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){
            uiState=VoiceUiState.State.ERROR_RECOVERY;
            stateText.setText("마이크 권한이 필요합니다 · 권한을 허용해주세요");
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO},REQ_AUDIO);
            return;
        }
        initSpeech();
    }

    private void initSpeech(){
        if(uiState==VoiceUiState.State.MIC_OFF||destroyed)return;
        if(recognizer!=null){talkButton.setEnabled(true);scheduleWakeListening(300);return;}
        if(!SpeechRecognizer.isRecognitionAvailable(this)){
            uiState=VoiceUiState.State.ERROR_RECOVERY;
            stateText.setText("음성인식을 사용할 수 없음 · 기기 설정을 확인해주세요");
            talkButton.setEnabled(false);handsFreeButton.setText("마이크: 사용 불가");return;
        }
        recognizer=SpeechRecognizer.createSpeechRecognizer(this);
        JSONObject impl=new JSONObject();try{impl.put("on_device",false);impl.put("on_device_available",android.os.Build.VERSION.SDK_INT>=31&&SpeechRecognizer.isOnDeviceRecognitionAvailable(this));impl.put("voice_recognition_service",android.provider.Settings.Secure.getString(getContentResolver(),"voice_recognition_service"));}catch(Exception ignored){}DiagnosticTrace.log("SR_IMPLEMENTATION",impl);
        recognizer.setRecognitionListener(new RecognitionListener(){
            @Override public void onReadyForSpeech(Bundle params){DiagnosticTrace.log("SR_ON_READY",null);uiState=VoiceUiState.State.LISTENING;stateText.setText(listenMode==ListenMode.WAKE?wakePrompt():(listenMode==ListenMode.FOLLOW_UP?followUpPrompt():"듣고 있습니다…"));}
            @Override public void onBeginningOfSpeech(){DiagnosticTrace.log("SR_BEGIN_SPEECH",null);if(listenMode==ListenMode.COMMAND||listenMode==ListenMode.FOLLOW_UP)stateText.setText("말씀하세요");}
            @Override public void onRmsChanged(float rmsdB){}
            @Override public void onBufferReceived(byte[] buffer){}
            @Override public void onEndOfSpeech(){
                DiagnosticTrace.log("SR_END_SPEECH",null);
                if(listenMode==ListenMode.COMMAND||listenMode==ListenMode.FOLLOW_UP){uiState=VoiceUiState.State.THINKING;stateText.setText("인식 중…"); try{JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("reason","end_of_speech");lifecycleEventId=voiceEvent("listening.stopped",listeningEventId,"info","household",p).getString("event_id");}catch(Exception ignored){}}
            }
            @Override public void onError(int error){
                JSONObject ep=new JSONObject();try{ep.put("error_code",error);ep.put("listen_mode",listenMode.name());}catch(Exception ignored){}DiagnosticTrace.log("SR_ERROR",ep);
                ListenMode failed=listenMode;listenMode=ListenMode.IDLE;
                if(uiState==VoiceUiState.State.MIC_OFF)return;
                if((error==SpeechRecognizer.ERROR_SPEECH_TIMEOUT||error==SpeechRecognizer.ERROR_NO_MATCH)&&failed==ListenMode.WAKE){
                    uiState=bridgeDegraded?VoiceUiState.State.OFFLINE_DEGRADED:VoiceUiState.State.READY;
                    stateText.setText(bridgeDegraded?offlinePrompt():wakePrompt());
                    if(handsFree)scheduleWakeListening(500);
                    return;
                }
                if((error==SpeechRecognizer.ERROR_SPEECH_TIMEOUT||error==SpeechRecognizer.ERROR_NO_MATCH)&&failed==ListenMode.FOLLOW_UP){
                    if(followUpNoMatchRetries<1){
                        followUpNoMatchRetries++;
                        uiState=VoiceUiState.State.READY;
                        stateText.setText(followUpPrompt());
                        main.postDelayed(()->startFollowUpListening(),450);
                    }else{
                        endConversation(true);
                    }
                    return;
                }
                uiState=VoiceUiState.State.ERROR_RECOVERY;talkButton.setEnabled(true);
                if(failed==ListenMode.COMMAND||failed==ListenMode.FOLLOW_UP){
                    try{JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("error_code",error);JSONObject f=voiceEvent("listening.failed",listeningEventId,"warning","household",p);JSONObject t=new JSONObject();t.put("language",recognitionLanguage());t.put("error_code",error);voiceEvent("transcript.failed",f.getString("event_id"),"warning","household",t);}catch(Exception ignored){}
                    transcriptText.setText("음성인식 오류 ("+error+")");
                    endConversation(true);
                    return;
                }
                stateText.setText("음성인식 오류 · 다시 시도합니다 ("+error+")");
                if(handsFree&&VoiceUiState.automaticWakeAllowed(uiState))scheduleWakeListening(350);
            }
            @Override public void onResults(Bundle results){
                ArrayList<String> matches=results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);DiagnosticTrace.logCandidates("SR_RESULTS",matches);ListenMode completed=listenMode;listenMode=ListenMode.IDLE;if(uiState!=VoiceUiState.State.MIC_OFF)uiState=VoiceUiState.State.READY;
                int count=matches==null?0:matches.size();
                if(completed==ListenMode.WAKE){
                    correlationId="corr-"+UUID.randomUUID();
                    try{JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("candidate_count",count);JSONObject candidate=voiceEvent("wake.candidate",null,"debug","household",p);lifecycleEventId=candidate.getString("event_id");
                        if(count==0){JSONObject r=new JSONObject();r.put("language",recognitionLanguage());r.put("candidate_count",0);r.put("reason","empty_result");voiceEvent("wake.rejected",lifecycleEventId,"debug","household",r);DiagnosticTrace.log("WAKE_REJECT",r);clearInteractionChain();if(handsFree)scheduleWakeListening(350);return;}
                        if(containsWakePhrase(matches)){conversationActive=true;followUpNoMatchRetries=0;JSONObject d=new JSONObject();d.put("language",recognitionLanguage());d.put("candidate_count",count);JSONObject detected=voiceEvent("wake.detected",lifecycleEventId,"info","household",d);DiagnosticTrace.log("WAKE_ACCEPT",d);listeningEventId=detected.getString("event_id");transcriptText.setText(profile==Profile.GRANDMA?"네, 말씀하세요.":"Listening…");stateText.setText("깨움 감지");JSONObject cp=new JSONObject();try{cp.put("delay_ms",250);}catch(Exception ignored){}DiagnosticTrace.log("COMMAND_LISTENER_REQUESTED",cp);main.postDelayed(()->startCommandListening(true),250);}
                        else{JSONObject r=new JSONObject();r.put("language",recognitionLanguage());r.put("candidate_count",count);r.put("reason","phrase_mismatch");voiceEvent("wake.rejected",lifecycleEventId,"debug","household",r);DiagnosticTrace.log("WAKE_REJECT",r);clearInteractionChain();if(handsFree)scheduleWakeListening(250);}
                    }catch(Exception ignored){clearInteractionChain();if(handsFree)scheduleWakeListening(350);}return;
                }
                if(count==0){
                    talkButton.setEnabled(true);
                    if(completed==ListenMode.FOLLOW_UP){
                        if(followUpNoMatchRetries<1){followUpNoMatchRetries++;uiState=VoiceUiState.State.READY;stateText.setText(followUpPrompt());main.postDelayed(()->startFollowUpListening(),450);}
                        else endConversation(true);
                        return;
                    }
                    if(completed==ListenMode.COMMAND){
                        try{JSONObject t=new JSONObject();t.put("language",recognitionLanguage());t.put("error_code",SpeechRecognizer.ERROR_NO_MATCH);voiceEvent("transcript.failed",lifecycleEventId,"warning","household",t);}catch(Exception ignored){}
                        endConversation(true);
                        return;
                    }
                    if(handsFree)scheduleWakeListening(350);
                    return;
                }
                String spoken=matches.get(0).trim();
                if(completed==ListenMode.FOLLOW_UP&&isConversationExit(spoken)){answerText.setText(recognitionLanguage().equals("en-US")?"Okay.":"네, 알겠습니다.");endConversation(true);return;}
                if(completed==ListenMode.COMMAND||completed==ListenMode.FOLLOW_UP){conversationActive=true;followUpNoMatchRetries=0;uiState=VoiceUiState.State.THINKING;transcriptText.setText((profile==Profile.GRANDMA?"할머니: ":"You: ")+spoken);stateText.setText("AI 처리 중…");sendToBridge(spoken,lifecycleEventId);}
            }
            @Override public void onPartialResults(Bundle partialResults){ArrayList<String> m=partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);DiagnosticTrace.logCandidates("SR_PARTIAL",m);if(listenMode!=ListenMode.COMMAND&&listenMode!=ListenMode.FOLLOW_UP)return;if(m!=null&&!m.isEmpty()&&!m.get(0).trim().isEmpty()){String text=m.get(0).trim();transcriptText.setText(text);try{JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("text",text);voiceEvent("transcript.partial",listeningEventId,"debug","sensitive",p);}catch(Exception ignored){}}}
            @Override public void onEvent(int eventType,Bundle params){JSONObject p=new JSONObject();try{p.put("event_type",eventType);}catch(Exception ignored){}DiagnosticTrace.log("SR_EVENT",p);}
        });
        uiState=bridgeDegraded?VoiceUiState.State.OFFLINE_DEGRADED:VoiceUiState.State.READY;
        talkButton.setEnabled(true);applyProfileUi();scheduleWakeListening(700);
    }

    private boolean containsWakePhrase(ArrayList<String> matches){for(String candidate:matches){String n=candidate.toLowerCase(Locale.ROOT).replace(" ","").replace("-","");if(n.contains("옥자")||n.contains("옥짜")||n.contains("okja")||n.contains("heyokja")||n.contains("okayokja"))return true;}return false;}
    private boolean isConversationExit(String spoken){
        String n=spoken.toLowerCase(Locale.ROOT).replace(" ","").replace(".","").replace("!","").replace("?","");
        return n.contains("고마워")||n.contains("감사해")||n.contains("됐어")||n.contains("그만")||n.equals("끝")||n.endsWith("끝내")||n.equals("stop")||n.contains("thanks")||n.contains("thankyou")||n.contains("that'sall")||n.contains("thatsall");
    }
    private Intent recognizerIntent(String lang,boolean partial){Intent i=new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);i.putExtra(RecognizerIntent.EXTRA_LANGUAGE,lang);i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE,lang);i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS,partial);i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS,5);return i;}
    private void scheduleWakeListening(long delayMs){
        JSONObject p=new JSONObject();try{p.put("delay_ms",delayMs);p.put("conversation_active",conversationActive);p.put("listen_mode",listenMode.name());}catch(Exception ignored){}DiagnosticTrace.log("REARM_SCHEDULED",p);
        if(!foreground||conversationActive||!handsFree||recognizer==null||destroyed||!VoiceUiState.automaticWakeAllowed(uiState))return;
        main.postDelayed(()->{
            if(foreground&&!conversationActive&&handsFree&&listenMode==ListenMode.IDLE&&!destroyed&&VoiceUiState.automaticWakeAllowed(uiState))startQuietWakeGate();
        },delayMs);
    }
    private void startQuietWakeGate(){
        if(!foreground||conversationActive||!handsFree||recognizer==null||destroyed||!VoiceUiState.microphoneAllowed(uiState))return;
        if(quietWakeGate==null){
            quietWakeGate=new QuietWakeGate(new QuietWakeGate.Callback(){
                @Override public void onSpeechActivity(){
                    if(foreground&&!conversationActive&&handsFree&&listenMode==ListenMode.IDLE&&!destroyed&&VoiceUiState.microphoneAllowed(uiState))startWakeListening();
                }
                @Override public void onFailure(String reason){
                    JSONObject p=new JSONObject();try{p.put("reason",reason);}catch(Exception ignored){}DiagnosticTrace.log("GATE_FAILURE",p);
                    if(destroyed||uiState==VoiceUiState.State.MIC_OFF)return;
                    uiState=VoiceUiState.State.ERROR_RECOVERY;
                    stateText.setText("조용한 깨움 대기 실패 · 지금 말하기를 사용해주세요");
                    talkButton.setEnabled(true);
                }
            });
        }
        if(!quietWakeGate.isRunning()){
            DiagnosticTrace.beginAttempt();DiagnosticTrace.log("GATE_RESTART",null);
            uiState=bridgeDegraded?VoiceUiState.State.OFFLINE_DEGRADED:VoiceUiState.State.READY;
            stateText.setText(bridgeDegraded?offlinePrompt():wakePrompt());
            quietWakeGate.start();
        }
    }
    private void stopQuietWakeGate(){if(quietWakeGate!=null)quietWakeGate.stop();}
    private void startWakeListening(){if(!foreground||conversationActive||!handsFree||recognizer==null||destroyed||!VoiceUiState.microphoneAllowed(uiState))return;stopQuietWakeGate();try{DiagnosticTrace.log("SR_CANCEL_REQUESTED",null);recognizer.cancel();DiagnosticTrace.log("SR_CANCEL_RETURNED",null);listenMode=ListenMode.WAKE;uiState=bridgeDegraded?VoiceUiState.State.OFFLINE_DEGRADED:VoiceUiState.State.READY;stateText.setText(bridgeDegraded?offlinePrompt():wakePrompt());DiagnosticTrace.nextGeneration();DiagnosticTrace.log("SR_START_REQUESTED",null);recognizer.startListening(recognizerIntent(recognitionLanguage(),false));DiagnosticTrace.log("SR_START_RETURNED",null);}catch(Exception e){JSONObject p=new JSONObject();try{p.put("error",e.getClass().getSimpleName());}catch(Exception ignored){}DiagnosticTrace.log("SR_START_EXCEPTION",p);listenMode=ListenMode.IDLE;uiState=VoiceUiState.State.ERROR_RECOVERY;stateText.setText("음성인식 시작 실패 · 다시 시도합니다");scheduleWakeListening(750);}}
    private void startCommandListening(boolean fromWake){
        if(!foreground)return;
        if(uiState==VoiceUiState.State.MIC_OFF){renderMicOff();return;}
        if(recognizer==null||destroyed){initSpeech();if(recognizer==null)return;}
        try{stopQuietWakeGate();if(correlationId.isEmpty())correlationId="corr-"+UUID.randomUUID();DiagnosticTrace.log("SR_CANCEL_REQUESTED",null);recognizer.cancel();DiagnosticTrace.log("SR_CANCEL_RETURNED",null);listenMode=ListenMode.COMMAND;uiState=VoiceUiState.State.LISTENING;talkButton.setEnabled(false);answerText.setText("");stateText.setText("듣고 있습니다…");JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("entrypoint",fromWake?"wake":"button");JSONObject listening=voiceEvent("listening.started",listeningEventId,"info","household",p);listeningEventId=listening.getString("event_id");lifecycleEventId=listeningEventId;DiagnosticTrace.nextGeneration();DiagnosticTrace.log("SR_START_REQUESTED",p);recognizer.startListening(recognizerIntent(recognitionLanguage(),true));DiagnosticTrace.log("SR_START_RETURNED",null);}
        catch(Exception e){JSONObject p=new JSONObject();try{p.put("error",e.getClass().getSimpleName());}catch(Exception ignored){}DiagnosticTrace.log("SR_START_EXCEPTION",p);listenMode=ListenMode.IDLE;uiState=VoiceUiState.State.ERROR_RECOVERY;talkButton.setEnabled(true);stateText.setText("음성인식 시작 실패 · 다시 시도해주세요");if(handsFree)scheduleWakeListening(700);}
    }
    private void startFollowUpListening(){
        if(!foreground||!conversationActive||!handsFree||uiState==VoiceUiState.State.MIC_OFF||bridgeDegraded||destroyed)return;
        if(recognizer==null){initSpeech();if(recognizer==null)return;}
        try{stopQuietWakeGate();DiagnosticTrace.log("SR_CANCEL_REQUESTED",null);recognizer.cancel();DiagnosticTrace.log("SR_CANCEL_RETURNED",null);listenMode=ListenMode.FOLLOW_UP;uiState=VoiceUiState.State.LISTENING;talkButton.setEnabled(false);stateText.setText(followUpPrompt());JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("entrypoint","follow_up");JSONObject listening=voiceEvent("listening.started",lifecycleEventId,"info","household",p);listeningEventId=listening.getString("event_id");lifecycleEventId=listeningEventId;DiagnosticTrace.nextGeneration();DiagnosticTrace.log("SR_START_REQUESTED",p);recognizer.startListening(recognizerIntent(recognitionLanguage(),true));DiagnosticTrace.log("SR_START_RETURNED",null);}
        catch(Exception e){endConversation(true);}
    }
    private void resetListening(){listenMode=ListenMode.IDLE;if(recognizer!=null)try{DiagnosticTrace.log("SR_CANCEL_REQUESTED",null);recognizer.cancel();DiagnosticTrace.log("SR_CANCEL_RETURNED",null);}catch(Exception ignored){}}
    private void endConversation(boolean resumeWake){interactionEpoch++;conversationActive=false;followUpNoMatchRetries=0;resetListening();clearInteractionChain();if(uiState!=VoiceUiState.State.MIC_OFF){uiState=bridgeDegraded?VoiceUiState.State.OFFLINE_DEGRADED:VoiceUiState.State.READY;stateText.setText(bridgeDegraded?offlinePrompt():wakePrompt());talkButton.setEnabled(true);if(resumeWake&&handsFree) scheduleWakeListening(650);}}

    private void sendToBridge(String prompt,String causationId){
        final String lang=recognitionLanguage();final String profileName=profile==Profile.GRANDMA?"grandma":"personal";final int requestEpoch=interactionEpoch;final JSONObject request;
        try{JSONObject p=new JSONObject();p.put("profile",profileName);p.put("language",lang);p.put("text",prompt);request=voiceEvent("transcript.final",causationId,"info","sensitive",p);}
        catch(Exception error){uiState=VoiceUiState.State.ERROR_RECOVERY;stateText.setText("이벤트 생성 실패 · 다시 시도해주세요");talkButton.setEnabled(true);return;}
        ioPool.execute(()->{
            String result;boolean degraded=false;
            try(Socket socket=new Socket()){
                socket.connect(new InetSocketAddress("127.0.0.1",PORT),3000);socket.setSoTimeout(90000);byte[] out=request.toString().getBytes(StandardCharsets.UTF_8);if(out.length<1||out.length>MAX_BRIDGE_PACKET_BYTES)throw new IllegalStateException("Bad request length");DataOutputStream dos=new DataOutputStream(socket.getOutputStream());DataInputStream dis=new DataInputStream(socket.getInputStream());dos.writeInt(out.length);dos.write(out);dos.flush();int len=dis.readInt();if(len<1||len>MAX_BRIDGE_PACKET_BYTES)throw new IllegalStateException("Bad reply length");byte[] in=new byte[len];dis.readFully(in);JSONObject response=new JSONObject(new String(in,StandardCharsets.UTF_8));OkjaEventEnvelope.requireResponseFor(response,request);JSONObject rp=response.getJSONObject("payload");if(response.getString("event_type").equals("assistant.failed")){degraded=true;result=lang.equals("en-US")?"AI bridge unavailable. Please try again.":"AI 브리지 응답 실패 · 다시 시도해주세요";}else{result=rp.getString("text");}
            }catch(Exception e){degraded=true;String detail=e.getClass().getSimpleName();String message=e.getMessage();if(message!=null&&!message.trim().isEmpty()){message=message.replace('\n',' ').replace('\r',' ').trim();if(message.length()>120)message=message.substring(0,120);detail += ": "+message;}result=lang.equals("en-US")?"Bridge diagnostic · "+detail:"브리지 진단 · "+detail;}
            final String reply=result;final boolean degradedResult=degraded;
            main.post(()->{
                if(destroyed||requestEpoch!=interactionEpoch||uiState==VoiceUiState.State.MIC_OFF)return;
                bridgeDegraded=degradedResult;
                if(degradedResult){answerText.setText(reply);endConversation(true);return;}
                uiState=VoiceUiState.State.THINKING;
                answerText.setText(reply);stateText.setText("답변 중…");talkButton.setEnabled(VoiceUiState.manualTalkEnabled(uiState));speak(reply,lang);
            });
        });
    }
    private void initTts(){
        ttsReady=false;
        tts=new TextToSpeech(this,status->{
            if(status!=TextToSpeech.SUCCESS){main.post(()->{ttsReady=false;if(!destroyed){stateText.setText("음성 출력 초기화 실패 · 화면 답변만 사용합니다");}});return;}
            ttsReady=true;
            tts.setSpeechRate(1.02f);
            tts.setOnUtteranceProgressListener(new UtteranceProgressListener(){
                @Override public void onStart(String id){main.post(()->{resetListening();if(uiState!=VoiceUiState.State.MIC_OFF){uiState=bridgeDegraded?VoiceUiState.State.OFFLINE_DEGRADED:VoiceUiState.State.THINKING;stateText.setText(bridgeDegraded?offlinePrompt():"답변 중…");}});}
                @Override public void onDone(String id){main.post(()->{listenMode=ListenMode.IDLE;if(uiState==VoiceUiState.State.MIC_OFF){renderMicOff();return;}if(foreground&&!bridgeDegraded&&handsFree&&conversationActive){uiState=VoiceUiState.State.READY;stateText.setText(followUpPrompt());talkButton.setEnabled(true);main.postDelayed(()->startFollowUpListening(),350);}else{endConversation(true);}});}
                @Override public void onError(String id){main.post(()->{endConversation(true);if(uiState!=VoiceUiState.State.MIC_OFF){uiState=VoiceUiState.State.ERROR_RECOVERY;stateText.setText("음성 출력 오류 · 화면에서 답변을 확인해주세요");talkButton.setEnabled(true);}});}
            });
        });
    }
    private void speak(String text,String lang){
        if(tts==null||!ttsReady){answerText.setText(text);endConversation(true);stateText.setText("음성 출력 준비 안 됨 · 화면에서 답변을 확인해주세요");return;}
        resetListening();
        int available=tts.setLanguage(lang.equals("en-US")?Locale.US:Locale.KOREA);
        if(available==TextToSpeech.LANG_MISSING_DATA||available==TextToSpeech.LANG_NOT_SUPPORTED){endConversation(true);stateText.setText("선택 언어 음성 출력 불가 · 화면에서 답변을 확인해주세요");return;}
        int status=tts.speak(text,TextToSpeech.QUEUE_FLUSH,null,"aihub-reply");
        if(status==TextToSpeech.ERROR){endConversation(true);stateText.setText("음성 출력 시작 실패 · 화면에서 답변을 확인해주세요");}
    }
    private JSONObject voiceEvent(String eventType,String causationId,String severity,String privacyClass,JSONObject payload)throws Exception{if(correlationId.isEmpty())correlationId="corr-"+UUID.randomUUID();JSONObject event=OkjaEventEnvelope.create(eventType,deviceId,profile==Profile.GRANDMA?"profile-grandma":"profile-personal",sessionId,correlationId,causationId,"android.voice",severity,privacyClass,"volatile",payload);return eventLedger.record(event);}
    private void clearInteractionChain(){correlationId="";lifecycleEventId=null;listeningEventId=null;}
    @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] grantResults){super.onRequestPermissionsResult(requestCode,permissions,grantResults);if(requestCode==REQ_AUDIO&&grantResults.length>0&&grantResults[0]==PackageManager.PERMISSION_GRANTED){handsFree=true;uiState=VoiceUiState.State.READY;initSpeech();}else{handsFree=false;uiState=VoiceUiState.State.ERROR_RECOVERY;talkButton.setEnabled(false);handsFreeButton.setText("마이크: 권한 필요");stateText.setText("마이크 권한이 필요합니다 · 설정에서 허용해주세요");}}
    @Override protected void onPause(){
        foreground=false;interactionEpoch++;conversationActive=false;followUpNoMatchRetries=0;main.removeCallbacksAndMessages(null);stopQuietWakeGate();resetListening();clearInteractionChain();if(tts!=null)try{tts.stop();}catch(Exception ignored){}super.onPause();
    }
    @Override protected void onResume(){
        super.onResume();foreground=true;if(destroyed||uiState==VoiceUiState.State.MIC_OFF)return;if(checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED){uiState=bridgeDegraded?VoiceUiState.State.OFFLINE_DEGRADED:VoiceUiState.State.READY;talkButton.setEnabled(recognizer!=null);scheduleWakeListening(350);}
    }
    @Override protected void onDestroy(){destroyed=true;foreground=false;ttsReady=false;interactionEpoch++;main.removeCallbacksAndMessages(null);stopQuietWakeGate();eventLedger.clear();if(recognizer!=null){DiagnosticTrace.log("SR_DESTROYED",null);recognizer.destroy();}if(tts!=null){tts.stop();tts.shutdown();}ioPool.shutdownNow();super.onDestroy();}
}
