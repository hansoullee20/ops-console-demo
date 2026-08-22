package com.soul.aihub

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.os.SystemClock
import android.text.InputType
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.soul.aihub.voice.AudioEngine
import com.soul.aihub.voice.PorcupineKoreanModelProvisioner
import com.soul.aihub.voice.PorcupinePcmWakeDetector
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Fold4 smoke-test surface for Porcupine using Okja's existing single-owner PCM path.
 *
 * The AccessKey is never persisted by this Activity. Provisioning may use network once; wake
 * inference after provisioning is local and receives only AudioEngine frames.
 *
 * Raw detections shown here are NOT a false-wake metric because this screen has no intentional-wake
 * annotations. Release wake scoring remains in WakeBenchmarkHarness / the long-recording evaluator.
 */
class PorcupineWakeActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val running = AtomicBoolean(false)

    private var audio: AudioEngine? = null
    private var detector: PorcupinePcmWakeDetector? = null
    private var collectorJob: Job? = null
    private var listeningStartedNs: Long = 0L
    private var detectionCount: Int = 0

    private lateinit var accessKeyInput: EditText
    private lateinit var sensitivityInput: EditText
    private lateinit var stateText: TextView
    private lateinit var resultText: TextView
    private lateinit var startButton: Button
    private lateinit var stopButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_AUDIO)
        }
    }

    private fun buildUi() {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 38, 32, 32)
            gravity = Gravity.CENTER_HORIZONTAL
            setBackgroundColor(Color.rgb(16, 16, 18))
        }

        root.addView(text("옥자 · Porcupine PCM Smoke Test", 24f, Color.WHITE))
        root.addView(text("옥자야 · low-level PCM · no second microphone", 14f, Color.LTGRAY))

        accessKeyInput = EditText(this).apply {
            hint = "Picovoice AccessKey (not saved)"
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            isSingleLine = true
        }
        sensitivityInput = EditText(this).apply {
            hint = "sensitivity 0..1"
            setText("0.5")
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            inputType = InputType.TYPE_CLASS_NUMBER or
                InputType.TYPE_NUMBER_FLAG_DECIMAL or
                InputType.TYPE_NUMBER_FLAG_SIGNED
            isSingleLine = true
        }
        root.addView(accessKeyInput)
        root.addView(sensitivityInput)

        stateText = text("STOPPED", 17f, Color.rgb(180, 220, 255))
        resultText = text(
            "처음 시작할 때 한국어 .pv 다운로드/검증과 ‘옥자야’ .ppn 생성이 수행될 수 있습니다.\n" +
                "이 화면의 raw detection count는 false-wake 지표가 아닙니다.",
            14f,
            Color.LTGRAY,
        ).apply { gravity = Gravity.START }
        root.addView(stateText)

        startButton = button("Provision → Start PCM wake test")
        startButton.setOnClickListener { startWakeTest() }
        root.addView(startButton)

        stopButton = button("Stop").apply { isEnabled = false }
        stopButton.setOnClickListener { stopWakeTest("STOPPED") }
        root.addView(stopButton)
        root.addView(resultText)

        val scroll = ScrollView(this)
        scroll.addView(root)
        setContentView(scroll)
    }

    private fun startWakeTest() {
        if (!running.compareAndSet(false, true)) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            running.set(false)
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_AUDIO)
            return
        }

        val accessKey = accessKeyInput.text.toString().trim()
        val sensitivity = sensitivityInput.text.toString().toFloatOrNull()
        if (accessKey.isBlank()) {
            running.set(false)
            stateText.text = "FAILED · AccessKey required"
            return
        }
        if (sensitivity == null || sensitivity !in 0f..1f) {
            running.set(false)
            stateText.text = "FAILED · sensitivity must be 0..1"
            return
        }

        accessKeyInput.isEnabled = false
        sensitivityInput.isEnabled = false
        startButton.isEnabled = false
        stopButton.isEnabled = false
        stateText.text = "PROVISIONING · network may be used once"
        resultText.text = "Korean model integrity check + 옥자야 keyword provisioning…"

        scope.launch {
            try {
                val models = PorcupineKoreanModelProvisioner(this@PorcupineWakeActivity)
                    .provision(accessKey)
                sessionAccessKey = accessKey
                val localDetector = PorcupinePcmWakeDetector.create(
                    context = this@PorcupineWakeActivity,
                    accessKey = accessKey,
                    keywordPath = models.keywordPath,
                    modelPath = models.modelPath,
                    keyword = models.phrase,
                    sensitivity = sensitivity,
                )
                val localAudio = AudioEngine()

                detector = localDetector
                audio = localAudio
                detectionCount = 0
                listeningStartedNs = SystemClock.elapsedRealtimeNanos()

                collectorJob = scope.launch(
                    context = Dispatchers.Default,
                    start = CoroutineStart.UNDISPATCHED,
                ) {
                    localAudio.frames.collect { frame ->
                        val detection = localDetector.accept(frame)
                        if (detection != null) {
                            val count = ++detectionCount
                            val elapsedSeconds =
                                (SystemClock.elapsedRealtimeNanos() - listeningStartedNs) / 1_000_000_000.0
                            withContext(Dispatchers.Main) {
                                resultText.text = buildString {
                                    append("DETECTED: ").append(detection.keyword).append("\n")
                                    append("raw detections: ").append(count).append("\n")
                                    append("listening: ")
                                        .append(String.format(Locale.US, "%.1f s", elapsedSeconds))
                                        .append("\n")
                                    append("AudioEngine frame sequence: ").append(frame.sequence).append("\n")
                                    append("Porcupine: ").append(localDetector.engineVersion).append("\n")
                                    append("Porcupine frame samples: ")
                                        .append(localDetector.requiredFrameSamples).append("\n")
                                    append("sensitivity: ").append(sensitivity).append("\n")
                                    append("\nThis is a smoke test, not false-wakes/hour qualification.")
                                }
                            }
                        }
                    }
                }

                check(localAudio.start()) { "AudioEngine did not start" }
                stateText.text = "LISTENING · say ‘옥자야’"
                stopButton.isEnabled = true
                resultText.text = buildString {
                    append("Ready. Say ‘옥자야’.\n")
                    append("Porcupine: ").append(localDetector.engineVersion).append("\n")
                    append("required frame: ").append(localDetector.requiredFrameSamples).append(" samples\n")
                    append("sensitivity: ").append(sensitivity).append("\n")
                    append("AccessKey is held only in this running Activity/session.")
                }
            } catch (t: Throwable) {
                stopWakeTest("FAILED · ${t.javaClass.simpleName}: ${t.message ?: "unknown"}")
            }
        }
    }

    private fun stopWakeTest(state: String) {
        collectorJob?.cancel()
        collectorJob = null
        audio?.close()
        audio = null
        detector?.close()
        detector = null
        running.set(false)
        stateText.text = state
        accessKeyInput.isEnabled = true
        sensitivityInput.isEnabled = true
        startButton.isEnabled = true
        stopButton.isEnabled = false
    }

    private fun button(label: String) = Button(this).apply {
        isAllCaps = false
        text = label
        textSize = 17f
    }

    private fun text(value: String, sp: Float, color: Int) = TextView(this).apply {
        text = value
        textSize = sp
        setTextColor(color)
        gravity = Gravity.CENTER
        setPadding(8, 12, 8, 12)
    }

    override fun onDestroy() {
        stopWakeTest("DESTROYED")
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        @Volatile
        var sessionAccessKey: String? = null
            private set
        private const val REQ_AUDIO = 3301
    }
}
