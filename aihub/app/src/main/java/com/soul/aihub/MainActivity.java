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
    private enum ListenMode { IDLE, WAKE, COMMAND }

    private Profile profile = Profile.PERSONAL;
    private String personalLanguage = "ko-KR";
    private ListenMode listenMode = ListenMode.IDLE;
    private boolean handsFree = true;
    private boolean destroyed = false;
    private String deviceId;
    private String sessionId;
    private String correlationId = "";
    private String lifecycleEventId;
    private String listeningEventId;

    private TextView titleText, stateText, transcriptText, answerText;
    private Button profileButton, languageButton, handsFreeButton, talkButton;
    private SpeechRecognizer recognizer;
    private TextToSpeech tts;
    private final VoiceEventLedger eventLedger = new VoiceEventLedger(128);
    private final ExecutorService ioPool = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
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
        profileButton=button(); profileButton.setOnClickListener(v->{ profile=profile==Profile.PERSONAL?Profile.GRANDMA:Profile.PERSONAL; clearInteractionChain(); resetListening(); applyProfileUi(); scheduleWakeListening(400); });
        languageButton=button(); languageButton.setOnClickListener(v->{ if(profile==Profile.PERSONAL){ personalLanguage=personalLanguage.equals("ko-KR")?"en-US":"ko-KR"; clearInteractionChain(); resetListening(); applyProfileUi(); scheduleWakeListening(400); }});
        handsFreeButton=button(); handsFreeButton.setOnClickListener(v->{ handsFree=!handsFree; if(handsFree){handsFreeButton.setText("웨이크워드: 켜짐");scheduleWakeListening(200);}else{resetListening();handsFreeButton.setText("웨이크워드: 꺼짐");stateText.setText("버튼 모드");}});
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
        handsFreeButton.setText(handsFree?"웨이크워드: 켜짐":"웨이크워드: 꺼짐");answerText.setText("");stateText.setText(recognizer!=null&&handsFree?wakePrompt():"준비됨 · "+recognitionLanguage());
    }
    private String wakePrompt(){return recognitionLanguage().equals("en-US")?"Waiting · 'Okja / Hey Okja'":"대기 중 · '옥자 / 옥자야'";}
    private String recognitionLanguage(){return profile==Profile.GRANDMA?"ko-KR":personalLanguage;}

    private void initSpeech(){
        if(!SpeechRecognizer.isRecognitionAvailable(this)){stateText.setText("이 기기에서 음성인식을 사용할 수 없음");talkButton.setEnabled(false);handsFreeButton.setEnabled(false);return;}
        recognizer=SpeechRecognizer.createSpeechRecognizer(this);
        recognizer.setRecognitionListener(new RecognitionListener(){
            @Override public void onReadyForSpeech(Bundle params){stateText.setText(listenMode==ListenMode.WAKE?wakePrompt():"듣고 있습니다…");}
            @Override public void onBeginningOfSpeech(){if(listenMode==ListenMode.COMMAND)stateText.setText("말씀하세요");}
            @Override public void onRmsChanged(float rmsdB){}
            @Override public void onBufferReceived(byte[] buffer){}
            @Override public void onEndOfSpeech(){
                if(listenMode==ListenMode.COMMAND){stateText.setText("인식 중…"); try{JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("reason","end_of_speech");lifecycleEventId=voiceEvent("listening.stopped",listeningEventId,"info","household",p).getString("event_id");}catch(Exception ignored){}}
            }
            @Override public void onError(int error){
                ListenMode failed=listenMode; listenMode=ListenMode.IDLE; talkButton.setEnabled(true);
                if(failed==ListenMode.COMMAND){try{JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("error_code",error);JSONObject f=voiceEvent("listening.failed",listeningEventId,"warning","household",p);JSONObject t=new JSONObject();t.put("language",recognitionLanguage());t.put("error_code",error);voiceEvent("transcript.failed",f.getString("event_id"),"warning","household",t);}catch(Exception ignored){} clearInteractionChain();}
                if(handsFree&&failed==ListenMode.WAKE)scheduleWakeListening(350); else if(handsFree&&failed==ListenMode.COMMAND){stateText.setText("다시 대기합니다");scheduleWakeListening(650);} else stateText.setText("음성인식 오류: "+error);
            }
            @Override public void onResults(Bundle results){
                ArrayList<String> matches=results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION); ListenMode completed=listenMode; listenMode=ListenMode.IDLE;
                int count=matches==null?0:matches.size();
                if(completed==ListenMode.WAKE){
                    correlationId="corr-"+UUID.randomUUID();
                    try{JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("candidate_count",count);JSONObject candidate=voiceEvent("wake.candidate",null,"debug","household",p);lifecycleEventId=candidate.getString("event_id");
                        if(count==0){JSONObject r=new JSONObject();r.put("language",recognitionLanguage());r.put("candidate_count",0);r.put("reason","empty_result");voiceEvent("wake.rejected",lifecycleEventId,"debug","household",r);clearInteractionChain();if(handsFree)scheduleWakeListening(350);return;}
                        if(containsWakePhrase(matches)){JSONObject d=new JSONObject();d.put("language",recognitionLanguage());d.put("candidate_count",count);JSONObject detected=voiceEvent("wake.detected",lifecycleEventId,"info","household",d);listeningEventId=detected.getString("event_id");transcriptText.setText(profile==Profile.GRANDMA?"네, 말씀하세요.":"Listening…");stateText.setText("깨움 감지");main.postDelayed(()->startCommandListening(true),250);}
                        else{JSONObject r=new JSONObject();r.put("language",recognitionLanguage());r.put("candidate_count",count);r.put("reason","phrase_mismatch");voiceEvent("wake.rejected",lifecycleEventId,"debug","household",r);clearInteractionChain();if(handsFree)scheduleWakeListening(250);}
                    }catch(Exception ignored){clearInteractionChain();if(handsFree)scheduleWakeListening(350);} return;
                }
                if(count==0){talkButton.setEnabled(true);if(completed==ListenMode.COMMAND){try{JSONObject t=new JSONObject();t.put("language",recognitionLanguage());t.put("error_code",SpeechRecognizer.ERROR_NO_MATCH);voiceEvent("transcript.failed",lifecycleEventId,"warning","household",t);}catch(Exception ignored){}clearInteractionChain();}if(handsFree)scheduleWakeListening(350);return;}
                String spoken=matches.get(0).trim();
                if(completed==ListenMode.COMMAND){transcriptText.setText((profile==Profile.GRANDMA?"할머니: ":"You: ")+spoken);stateText.setText("Claude에게 보내는 중…");sendToBridge(spoken,lifecycleEventId);}
            }
            @Override public void onPartialResults(Bundle partialResults){if(listenMode!=ListenMode.COMMAND)return;ArrayList<String> m=partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);if(m!=null&&!m.isEmpty()&&!m.get(0).trim().isEmpty()){String text=m.get(0).trim();transcriptText.setText(text);try{JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("text",text);voiceEvent("transcript.partial",listeningEventId,"debug","sensitive",p);}catch(Exception ignored){}}}
            @Override public void onEvent(int eventType,Bundle params){}
        });
        talkButton.setEnabled(true);applyProfileUi();scheduleWakeListening(700);
    }

    private boolean containsWakePhrase(ArrayList<String> matches){for(String candidate:matches){String n=candidate.toLowerCase(Locale.ROOT).replace(" ","").replace("-","");if(n.contains("옥자")||n.contains("옥짜")||n.contains("okja")||n.contains("heyokja")||n.contains("okayokja"))return true;}return false;}
    private Intent recognizerIntent(String lang,boolean partial){Intent i=new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);i.putExtra(RecognizerIntent.EXTRA_LANGUAGE,lang);i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE,lang);i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS,partial);i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS,5);return i;}
    private void scheduleWakeListening(long delayMs){if(!handsFree||recognizer==null||destroyed)return;main.postDelayed(()->{if(handsFree&&listenMode==ListenMode.IDLE&&!destroyed)startWakeListening();},delayMs);}
    private void startWakeListening(){if(!handsFree||recognizer==null||destroyed)return;try{recognizer.cancel();listenMode=ListenMode.WAKE;stateText.setText(wakePrompt());recognizer.startListening(recognizerIntent(recognitionLanguage(),false));}catch(Exception e){listenMode=ListenMode.IDLE;scheduleWakeListening(750);}}
    private void startCommandListening(boolean fromWake){
        if(recognizer==null||destroyed){initSpeech();if(recognizer==null)return;}
        try{if(correlationId.isEmpty())correlationId="corr-"+UUID.randomUUID();recognizer.cancel();listenMode=ListenMode.COMMAND;talkButton.setEnabled(false);answerText.setText("");stateText.setText("듣고 있습니다…");JSONObject p=new JSONObject();p.put("language",recognitionLanguage());p.put("entrypoint",fromWake?"wake":"button");JSONObject listening=voiceEvent("listening.started",listeningEventId,"info","household",p);listeningEventId=listening.getString("event_id");lifecycleEventId=listeningEventId;recognizer.startListening(recognizerIntent(recognitionLanguage(),true));}
        catch(Exception e){listenMode=ListenMode.IDLE;talkButton.setEnabled(true);stateText.setText("음성인식 시작 실패");if(handsFree)scheduleWakeListening(700);}
    }
    private void resetListening(){listenMode=ListenMode.IDLE;if(recognizer!=null)try{recognizer.cancel();}catch(Exception ignored){}}

    private void sendToBridge(String prompt,String causationId){
        final String lang=recognitionLanguage();final String profileName=profile==Profile.GRANDMA?"grandma":"personal";final JSONObject request;
        try{JSONObject p=new JSONObject();p.put("profile",profileName);p.put("language",lang);p.put("text",prompt);request=voiceEvent("transcript.final",causationId,"info","sensitive",p);}
        catch(Exception error){stateText.setText("이벤트 생성 실패");talkButton.setEnabled(true);return;}
        ioPool.execute(()->{String result;try(Socket socket=new Socket()){socket.connect(new InetSocketAddress("127.0.0.1",PORT),3000);socket.setSoTimeout(90000);byte[] out=request.toString().getBytes(StandardCharsets.UTF_8);DataOutputStream dos=new DataOutputStream(socket.getOutputStream());DataInputStream dis=new DataInputStream(socket.getInputStream());dos.writeInt(out.length);dos.write(out);dos.flush();int len=dis.readInt();if(len<0||len>2_000_000)throw new IllegalStateException("Bad reply length");byte[] in=new byte[len];dis.readFully(in);JSONObject response=new JSONObject(new String(in,StandardCharsets.UTF_8));OkjaEventEnvelope.requireResponseFor(response,request);JSONObject rp=response.getJSONObject("payload");result=response.getString("event_type").equals("assistant.response")?rp.getString("text"):rp.optString("message","Assistant request failed");}catch(Exception e){result="브리지/이벤트 오류: "+e.getClass().getSimpleName();}final String reply=result;main.post(()->{answerText.setText(reply);stateText.setText("답변 중…");talkButton.setEnabled(true);speak(reply,lang);});});
    }
    private void initTts(){tts=new TextToSpeech(this,status->{if(status==TextToSpeech.SUCCESS){tts.setSpeechRate(1.02f);tts.setOnUtteranceProgressListener(new UtteranceProgressListener(){@Override public void onStart(String id){main.post(()->{resetListening();stateText.setText("답변 중…");});}@Override public void onDone(String id){main.post(()->{clearInteractionChain();listenMode=ListenMode.IDLE;stateText.setText(handsFree?wakePrompt():"준비됨");if(handsFree)scheduleWakeListening(650);});}@Override public void onError(String id){main.post(()->{clearInteractionChain();listenMode=ListenMode.IDLE;if(handsFree)scheduleWakeListening(650);});}});}});}
    private void speak(String text,String lang){if(tts==null){clearInteractionChain();if(handsFree)scheduleWakeListening(500);return;}resetListening();tts.setLanguage(lang.equals("en-US")?Locale.US:Locale.KOREA);tts.speak(text,TextToSpeech.QUEUE_FLUSH,null,"aihub-reply");}
    private JSONObject voiceEvent(String eventType,String causationId,String severity,String privacyClass,JSONObject payload)throws Exception{if(correlationId.isEmpty())correlationId="corr-"+UUID.randomUUID();JSONObject event=OkjaEventEnvelope.create(eventType,deviceId,profile==Profile.GRANDMA?"profile-grandma":"profile-personal",sessionId,correlationId,causationId,"android.voice",severity,privacyClass,"volatile",payload);return eventLedger.record(event);}
    private void clearInteractionChain(){correlationId="";lifecycleEventId=null;listeningEventId=null;}
    @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] grantResults){super.onRequestPermissionsResult(requestCode,permissions,grantResults);if(requestCode==REQ_AUDIO&&grantResults.length>0&&grantResults[0]==PackageManager.PERMISSION_GRANTED)initSpeech();else stateText.setText("마이크 권한 필요");}
    @Override protected void onDestroy(){destroyed=true;main.removeCallbacksAndMessages(null);eventLedger.clear();if(recognizer!=null)recognizer.destroy();if(tts!=null){tts.stop();tts.shutdown();}ioPool.shutdownNow();super.onDestroy();}
}
