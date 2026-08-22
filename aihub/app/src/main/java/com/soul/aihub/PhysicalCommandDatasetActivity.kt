package com.soul.aihub

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.soul.aihub.voice.AudioEngine
import com.soul.aihub.voice.Pcm16UtteranceBuffer
import com.soul.aihub.voice.PcmContinuityTracker
import com.soul.aihub.voice.PhysicalCommandClass
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.takeWhile
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Fold4 data-capture surface for the five-class physical-command model.
 *
 * AudioEngine remains the sole microphone owner. Each trial saves raw 16 kHz mono PCM16 plus one
 * JSONL manifest row containing label, speaker/session/condition provenance, prompt, and
 * continuity-checked sample metadata. This activity intentionally does not train or authorize.
 */
class PhysicalCommandDatasetActivity : Activity() {
    private data class Prompt(
        val label: PhysicalCommandClass,
        val text: String,
    )

    private val prompts = listOf(
        Prompt(PhysicalCommandClass.TV_ON, "옥자 TV 켜줘"),
        Prompt(PhysicalCommandClass.TV_OFF, "옥자 TV 꺼줘"),
        Prompt(PhysicalCommandClass.AC_ON, "옥자 에어컨 켜줘"),
        Prompt(PhysicalCommandClass.AC_OFF, "옥자 에어컨 꺼줘"),
        Prompt(PhysicalCommandClass.TV_ON, "TV 좀 켜줘"),
        Prompt(PhysicalCommandClass.TV_OFF, "TV 좀 꺼줘"),
        Prompt(PhysicalCommandClass.AC_ON, "에어컨 좀 켜줘"),
        Prompt(PhysicalCommandClass.AC_OFF, "에어컨 좀 꺼줘"),
        Prompt(PhysicalCommandClass.OTHER, "옥자야 뭐하니"),
        Prompt(PhysicalCommandClass.OTHER, "오늘 날씨 어때"),
        Prompt(PhysicalCommandClass.OTHER, "TV 보고 싶다"),
        Prompt(PhysicalCommandClass.OTHER, "에어컨 시원하다"),
        Prompt(PhysicalCommandClass.OTHER, "TV 켜지 마"),
        Prompt(PhysicalCommandClass.OTHER, "에어컨 끄지 마"),
        Prompt(PhysicalCommandClass.OTHER, "TV 켜... 아니 꺼줘"),
        Prompt(PhysicalCommandClass.OTHER, "에어컨 꺼... 아니 켜줘"),
    )

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val running = AtomicBoolean(false)
    private val sessionId = UUID.randomUUID().toString()
    private var promptIndex = 0
    private var activeAudio: AudioEngine? = null

    private lateinit var promptText: TextView
    private lateinit var stateText: TextView
    private lateinit var statsText: TextView
    private lateinit var speakerIdInput: EditText
    private lateinit var conditionInput: EditText
    private lateinit var recordButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        renderPrompt()
        renderStats()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_AUDIO)
        }
    }

    private fun buildUi() {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 38, 32, 32)
            gravity = Gravity.CENTER_HORIZONTAL
            setBackgroundColor(Color.rgb(16, 16, 18))
        }
        root.addView(text("옥자 · Physical Command Dataset", 24f, Color.WHITE))
        root.addView(text("5-class PCM capture · AudioEngine only", 14f, Color.LTGRAY))

        speakerIdInput = EditText(this).apply {
            hint = "speaker id"
            setText(prefs.getString(PREF_SPEAKER_ID, "speaker-01"))
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            singleLine = true
        }
        conditionInput = EditText(this).apply {
            hint = "condition (quiet/tv/noise/...)"
            setText(prefs.getString(PREF_CONDITION, "quiet"))
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            singleLine = true
        }
        root.addView(text("Speaker ID", 14f, Color.LTGRAY))
        root.addView(speakerIdInput)
        root.addView(text("Condition", 14f, Color.LTGRAY))
        root.addView(conditionInput)

        promptText = text("", 22f, Color.WHITE)
        stateText = text("READY", 17f, Color.rgb(180, 220, 255))
        statsText = text("", 14f, Color.LTGRAY).apply { gravity = Gravity.START }
        root.addView(promptText)
        root.addView(stateText)

        val previous = button("이전 문구")
        previous.setOnClickListener {
            if (!running.get()) {
                promptIndex = (promptIndex - 1 + prompts.size) % prompts.size
                renderPrompt()
            }
        }
        root.addView(previous)

        val next = button("다음 문구")
        next.setOnClickListener {
            if (!running.get()) {
                promptIndex = (promptIndex + 1) % prompts.size
                renderPrompt()
            }
        }
        root.addView(next)

        recordButton = button("3초 녹음 → 라벨 저장")
        recordButton.setOnClickListener { captureCurrentPrompt() }
        root.addView(recordButton)
        root.addView(statsText)

        val scroll = ScrollView(this)
        scroll.addView(root)
        setContentView(scroll)
    }

    private fun captureCurrentPrompt() {
        if (!running.compareAndSet(false, true)) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            running.set(false)
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_AUDIO)
            return
        }

        val speakerId = speakerIdInput.text.toString().trim()
        val condition = conditionInput.text.toString().trim()
        if (speakerId.isBlank() || condition.isBlank()) {
            running.set(false)
            stateText.text = "FAILED · speaker id와 condition은 비워둘 수 없습니다"
            return
        }
        getSharedPreferences(PREFS_NAME, MODE_PRIVATE).edit()
            .putString(PREF_SPEAKER_ID, speakerId)
            .putString(PREF_CONDITION, condition)
            .apply()

        recordButton.isEnabled = false
        val prompt = prompts[promptIndex]
        scope.launch {
            try {
                stateText.text = "준비… 0.8초 뒤 말하세요"
                delay(800)
                stateText.text = "지금 말하세요 · 3초 녹음"
                val pcm = capturePcm(RECORD_SECONDS)
                val record = saveTrial(prompt, pcm, speakerId, condition)
                stateText.text = "SAVED · ${record.name}"
                renderStats()
            } catch (t: Throwable) {
                stateText.text = "FAILED · ${t.javaClass.simpleName}: ${t.message ?: "unknown"}"
            } finally {
                activeAudio?.close()
                activeAudio = null
                running.set(false)
                recordButton.isEnabled = true
            }
        }
    }

    private suspend fun capturePcm(seconds: Int): ShortArray {
        val targetSamples = AudioEngine.SAMPLE_RATE_HZ * seconds
        val buffer = Pcm16UtteranceBuffer(maxSamples = targetSamples + AudioEngine.SAMPLE_RATE_HZ)
        val continuity = PcmContinuityTracker()
        buffer.begin(ShortArray(0))
        val audio = AudioEngine(ringCapacityMs = AudioEngine.DEFAULT_RING_CAPACITY_MS)
        activeAudio = audio

        val collector = scope.async(
            context = Dispatchers.Default,
            start = CoroutineStart.UNDISPATCHED,
        ) {
            audio.frames
                .takeWhile { buffer.sampleCount() < targetSamples }
                .collect { frame ->
                    val observation = continuity.observe(frame)
                    check(observation.continuous) {
                        "PCM discontinuity: expected sequence=${observation.expectedSequence}, " +
                            "actual=${observation.actualSequence}, missingFrames=${observation.missingFrames}"
                    }
                    buffer.append(frame.samples)
                }
        }

        try {
            check(audio.start()) { "AudioEngine did not start" }
            withTimeout((seconds + 2L) * 1_000L) { collector.await() }
        } finally {
            audio.stop()
            collector.cancel()
        }
        return buffer.snapshot()
    }

    private fun saveTrial(
        prompt: Prompt,
        pcm: ShortArray,
        speakerId: String,
        condition: String,
    ): File {
        val root = datasetDir()
        val timestamp = System.currentTimeMillis()
        val stem = "$timestamp-${prompt.label.name.lowercase()}"
        val pcmFile = File(root, "$stem.pcm16le")
        val bytes = ByteBuffer.allocate(pcm.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        pcm.forEach { bytes.putShort(it) }
        val payload = bytes.array()
        FileOutputStream(pcmFile).use { it.write(payload) }

        val row = JSONObject().apply {
            put("schema", "okja.physical-command-corpus.v2")
            put("created_at_ms", timestamp)
            put("label", prompt.label.name)
            put("prompt", prompt.text)
            put("speaker_id", speakerId)
            put("session_id", sessionId)
            put("condition", condition)
            put("pcm_file", pcmFile.name)
            put("sample_rate_hz", AudioEngine.SAMPLE_RATE_HZ)
            put("channels", 1)
            put("encoding", "pcm_s16le")
            put("sample_count", pcm.size)
            put("duration_ms", pcm.size * 1000L / AudioEngine.SAMPLE_RATE_HZ)
            put("sha256", sha256(payload))
            put("capture_owner", "AudioEngine")
            put("pcm_continuity_verified", true)
            put("device_manufacturer", Build.MANUFACTURER)
            put("device_model", Build.MODEL)
            put("android_sdk_int", Build.VERSION.SDK_INT)
        }
        File(root, MANIFEST_NAME).appendText(row.toString() + "\n", Charsets.UTF_8)
        return pcmFile
    }

    private fun renderPrompt() {
        val prompt = prompts[promptIndex]
        promptText.text = "[${prompt.label.name}]\n“${prompt.text}”"
    }

    private fun renderStats() {
        val manifest = File(datasetDir(), MANIFEST_NAME)
        val counts = mutableMapOf<PhysicalCommandClass, Int>().withDefault { 0 }
        if (manifest.exists()) {
            manifest.forEachLine(Charsets.UTF_8) { line ->
                try {
                    val label = PhysicalCommandClass.valueOf(JSONObject(line).getString("label"))
                    counts[label] = counts.getValue(label) + 1
                } catch (_: Throwable) {
                    // Display is best-effort; training import validates every row strictly.
                }
            }
        }
        statsText.text = buildString {
            append("session: ").append(sessionId).append("\n")
            append("저장 위치: ").append(datasetDir().absolutePath).append("\n")
            PhysicalCommandClass.entries.forEach { label ->
                append(label.name).append(": ").append(counts.getValue(label)).append("\n")
            }
        }
    }

    private fun datasetDir(): File {
        val root = getExternalFilesDir(DATASET_DIR) ?: File(filesDir, DATASET_DIR)
        check(root.exists() || root.mkdirs()) { "Unable to create dataset directory" }
        return root
    }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { "%02x".format(it) }

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
        activeAudio?.close()
        activeAudio = null
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val REQ_AUDIO = 3201
        private const val RECORD_SECONDS = 3
        private const val DATASET_DIR = "okja-physical-command-dataset"
        private const val MANIFEST_NAME = "manifest.jsonl"
        private const val PREFS_NAME = "okja-command-dataset"
        private const val PREF_SPEAKER_ID = "speaker-id"
        private const val PREF_CONDITION = "condition"
    }
}
