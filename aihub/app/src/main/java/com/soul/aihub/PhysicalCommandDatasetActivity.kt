package com.soul.aihub

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import com.soul.aihub.voice.AudioEngine
import com.soul.aihub.voice.Pcm16UtteranceBuffer
import com.soul.aihub.voice.PcmContinuityTracker
import com.soul.aihub.voice.PcmWindow
import com.soul.aihub.voice.PhysicalCommandClass
import com.soul.aihub.voice.PorcupinePcmWakeDetector
import com.soul.aihub.voice.SherpaMoonshineBenchmarkEngine
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
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt

/**
 * Fold4 data-capture surface for the five-class physical-command model.
 *
 * AudioEngine remains the sole microphone owner. Each trial saves exactly 3.0 s of 16 kHz mono
 * PCM16 plus one JSONL manifest row containing label, speaker/session/condition provenance, prompt,
 * and continuity-checked sample metadata. Sanity mode writes separate non-training evidence.
 */
class PhysicalCommandDatasetActivity : Activity() {
    private data class Prompt(val label: PhysicalCommandClass, val text: String, val id: String? = null)
    private data class CaptureResult(val window: PcmWindow, val wakeFrameIndex: Long?)
    private data class AsrTiming(val initMs: Double, val decodeMs: Double?, val finalizeMs: Double?, val text: String)

    private val prompts = listOf(
        Prompt(PhysicalCommandClass.TV_ON, "옥자 TV 켜줘"),
        Prompt(PhysicalCommandClass.TV_OFF, "옥자 TV 꺼줘"),
        Prompt(PhysicalCommandClass.AC_ON, "옥자 에어컨 켜줘"),
        Prompt(PhysicalCommandClass.AC_OFF, "옥자 에어컨 꺼줘"),
        Prompt(PhysicalCommandClass.TV_ON, "옥자야 TV 켜줘"),
        Prompt(PhysicalCommandClass.TV_OFF, "옥자야 TV 꺼줘"),
        Prompt(PhysicalCommandClass.AC_ON, "옥자야 에어컨 켜줘"),
        Prompt(PhysicalCommandClass.AC_OFF, "옥자야 에어컨 꺼줘"),
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
    private val sanityPrompts = listOf(
        Prompt(PhysicalCommandClass.TV_ON, "옥자야 TV 켜줘", "S01"), Prompt(PhysicalCommandClass.TV_OFF, "옥자야 TV 꺼줘", "S02"),
        Prompt(PhysicalCommandClass.AC_ON, "옥자야 에어컨 켜줘", "S03"), Prompt(PhysicalCommandClass.AC_OFF, "옥자야 에어컨 꺼줘", "S04"),
        Prompt(PhysicalCommandClass.TV_ON, "옥자야 TV 좀 켜줘", "S05"), Prompt(PhysicalCommandClass.TV_OFF, "옥자야 TV 좀 꺼줘", "S06"),
        Prompt(PhysicalCommandClass.AC_ON, "옥자야 에어컨 좀 켜줘", "S07"), Prompt(PhysicalCommandClass.AC_OFF, "옥자야 에어컨 좀 꺼줘", "S08"),
        Prompt(PhysicalCommandClass.OTHER, "옥자야 뭐하니", "S09"), Prompt(PhysicalCommandClass.OTHER, "옥자야 지금 몇 시야", "S10"),
        Prompt(PhysicalCommandClass.OTHER, "옥자야 오늘 날씨 어때", "S11"), Prompt(PhysicalCommandClass.OTHER, "옥자야 잘 자", "S12"),
    )

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val running = AtomicBoolean(false)
    private val sessionId = UUID.randomUUID().toString()
    private val installedApkSha256 by lazy { sha256(File(applicationInfo.sourceDir)) }
    private var promptIndex = 0
    private var captureEpoch = 0L
    private var activeAudio: AudioEngine? = null

    private lateinit var promptText: TextView
    private lateinit var stateText: TextView
    private lateinit var statsText: TextView
    private lateinit var speakerIdInput: EditText
    private lateinit var conditionInput: EditText
    private lateinit var sanityMode: Switch
    private lateinit var recordButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        selectFirstIncompleteSanityPrompt()
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
            isSingleLine = true
        }
        conditionInput = EditText(this).apply {
            hint = "condition (quiet/tv/noise/...)"
            setText(prefs.getString(PREF_CONDITION, "quiet"))
            setTextColor(Color.WHITE)
            setHintTextColor(Color.GRAY)
            isSingleLine = true
        }
        root.addView(text("Speaker ID", 14f, Color.LTGRAY))
        root.addView(speakerIdInput)
        root.addView(text("Condition", 14f, Color.LTGRAY))
        root.addView(conditionInput)
        sanityMode = Switch(this).apply {
            text = "Sanity mode · 12문장 × 각 5회"
            setTextColor(Color.WHITE)
            isChecked = true
            setOnCheckedChangeListener { _, checked ->
                promptIndex = 0
                if (checked) selectFirstIncompleteSanityPrompt()
                renderPrompt()
                renderStats()
            }
        }
        root.addView(sanityMode)

        promptText = text("", 22f, Color.WHITE)
        stateText = text("READY", 17f, Color.rgb(180, 220, 255))
        statsText = text("", 14f, Color.LTGRAY).apply { gravity = Gravity.START }
        root.addView(promptText)
        root.addView(stateText)

        val previous = button("이전 문구")
        previous.setOnClickListener {
            if (!running.get()) {
                promptIndex = (promptIndex - 1 + activePrompts().size) % activePrompts().size
                renderPrompt()
            }
        }
        root.addView(previous)

        val next = button("다음 문구")
        next.setOnClickListener {
            if (!running.get()) {
                promptIndex = (promptIndex + 1) % activePrompts().size
                renderPrompt()
            }
        }
        root.addView(next)

        recordButton = button("3초 녹음 → 라벨 저장")
        recordButton.setOnClickListener { captureCurrentPrompt() }
        root.addView(recordButton)

        val resetSanity = button("Sanity 기록 전체 초기화")
        resetSanity.setOnClickListener {
            if (running.get()) return@setOnClickListener
            if (!sanityMode.isChecked) {
                stateText.text = "Sanity mode를 먼저 켜세요"
                return@setOnClickListener
            }
            AlertDialog.Builder(this)
                .setTitle("Sanity 기록 초기화")
                .setMessage("저장된 sanity-v2 PCM과 JSON을 모두 삭제하고 0/60부터 다시 시작합니다.")
                .setNegativeButton("취소", null)
                .setPositiveButton("초기화") { _, _ -> resetSanityProgress() }
                .show()
        }
        root.addView(resetSanity)
        root.addView(statsText)

        val scroll = ScrollView(this)
        scroll.addView(root)
        setContentView(scroll)
    }

    private fun activePrompts(): List<Prompt> = if (sanityMode.isChecked) sanityPrompts else prompts

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

        if (sanityMode.isChecked) {
            val prompt = sanityPrompts[promptIndex]
            if (sanityCount(prompt.id!!) >= SANITY_REPEATS_PER_PHRASE) {
                running.set(false)
                if (selectFirstIncompleteSanityPrompt()) {
                    stateText.text = "이 문장은 5/5 완료 · 다음 미완료 문장으로 이동"
                    renderPrompt()
                } else {
                    stateText.text = "SANITY COMPLETE · 60/60"
                }
                return
            }
        }

        recordButton.isEnabled = false
        val prompt = activePrompts()[promptIndex]
        scope.launch {
            try {
                if (sanityMode.isChecked) runSanity(prompt) else {
                    stateText.text = "준비… 0.8초 뒤 말하세요"
                    delay(800)
                    stateText.text = "지금 말하세요 · 3초 녹음"
                    val pcm = capturePcm(RECORD_SECONDS).window.samples
                    val record = saveTrial(prompt, pcm, speakerId, condition)
                    stateText.text = "SAVED · ${record.name}"
                    renderStats()
                }
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

    private suspend fun runSanity(prompt: Prompt) {
        check(hasMoonshineAssets()) { "Moonshine assets missing; use Moonshine benchmark APK" }
        stateText.text = "BOOTSTRAP · 준비… 1.2초 뒤 말하세요"
        val cue = scope.launch { delay(SANITY_CUE_DELAY_MS); stateText.text = "BOOTSTRAP · 지금 말하세요" }
        captureEpoch = SystemClock.elapsedRealtimeNanos()
        val capture = try { capturePcm(RECORD_SECONDS) } finally { cue.cancel() }
        val runId = UUID.randomUUID().toString()
        saveSanityPcm(runId, capture.window.samples)
        val onset = checkNotNull(detectOnsetSample(capture.window.samples)) { "SANITY STOP: utterance onset not found" }
        val asr = withContext(Dispatchers.Default) { runMoonshine(capture.window) }
        val row = JSONObject().apply {
            put("schema", "okja.pipeline-sanity.v2")
            put("run_id", runId)
            put("phrase_id", checkNotNull(prompt.id))
            put("prompt_text", prompt.text)
            put("capture_epoch", captureEpoch)
            put("sample_rate_hz", AudioEngine.SAMPLE_RATE_HZ)
            put("pcm_start_sample", capture.window.startSampleIndex)
            put("pcm_end_sample", capture.window.endSampleIndexExclusive)
            put("continuity_ok", true)
            put("onset_sample", onset)
            put("wake_engine", "none-bootstrap")
            put("wake_model_name", JSONObject.NULL)
            put("wake_model_sha256", JSONObject.NULL)
            put("wake_config_sha256", JSONObject.NULL)
            put("wake_detector_init_ms", JSONObject.NULL)
            put("wake_engine_warmup_ms", JSONObject.NULL)
            put("wake_frame_index", JSONObject.NULL)
            put("wake_decision_sample", JSONObject.NULL)
            put("keyword_end_sample", JSONObject.NULL)
            put("keyword_end_to_wake_ms", JSONObject.NULL)
            put("onset_to_wake_ms", JSONObject.NULL)
            put("preroll_start_sample", JSONObject.NULL)
            put("asr_init_ms", asr.initMs)
            put("asr_decode_ms", asr.decodeMs ?: JSONObject.NULL)
            put("asr_finalize_ms", asr.finalizeMs ?: JSONObject.NULL)
            put("transcript", asr.text)
            put("apk_sha256", installedApkSha256)
        }
        File(sanityDir(), SANITY_JSONL).appendText(row.toString() + "\n", Charsets.UTF_8)

        val completed = sanityCount(prompt.id!!)
        if (completed >= SANITY_REPEATS_PER_PHRASE) {
            if (selectFirstIncompleteSanityPrompt()) {
                stateText.text = "${prompt.id} 5/5 완료 · 다음 ${sanityPrompts[promptIndex].id}"
            } else {
                stateText.text = "SANITY COMPLETE · 60/60"
            }
        } else {
            stateText.text = "${prompt.id} 저장 · $completed/$SANITY_REPEATS_PER_PHRASE"
        }
        renderPrompt()
        renderStats()
    }

    private suspend fun capturePcm(seconds: Int, wakeDetector: PorcupinePcmWakeDetector? = null): CaptureResult {
        val targetSamples = AudioEngine.SAMPLE_RATE_HZ * seconds
        val buffer = Pcm16UtteranceBuffer(maxSamples = targetSamples)
        val continuity = PcmContinuityTracker()
        buffer.begin(ShortArray(0))
        val audio = AudioEngine(ringCapacityMs = AudioEngine.DEFAULT_RING_CAPACITY_MS)
        activeAudio = audio
        var firstFrame = true
        var wakeFrameIndex: Long? = null

        val collector = scope.async(
            context = Dispatchers.Default,
            start = CoroutineStart.UNDISPATCHED,
        ) {
            audio.frames
                .takeWhile { buffer.sampleCount() < targetSamples }
                .collect { frame ->
                    if (firstFrame) {
                        check(frame.sequence == 0L && frame.startSampleIndex == 0L) {
                            "capture did not start at AudioEngine epoch origin: " +
                                "sequence=${frame.sequence}, sample=${frame.startSampleIndex}"
                        }
                        firstFrame = false
                    }
                    val observation = continuity.observe(frame)
                    check(observation.continuous) { "SANITY STOP: PCM discontinuity" }
                    if (wakeFrameIndex == null && wakeDetector?.accept(frame) != null) wakeFrameIndex = frame.sequence
                    val remaining = targetSamples - buffer.sampleCount()
                    if (remaining > 0) {
                        if (frame.samples.size <= remaining) buffer.append(frame.samples)
                        else buffer.append(frame.samples.copyOf(remaining))
                    }
                }
        }

        try {
            check(audio.start()) { "AudioEngine did not start" }
            withTimeout((seconds + 2L) * 1_000L) { collector.await() }
        } finally {
            audio.stop()
            collector.cancel()
        }
        val result = buffer.snapshot()
        check(result.size == targetSamples) { "capture length mismatch: ${result.size} != $targetSamples samples" }
        return CaptureResult(PcmWindow(result, 0L, result.size.toLong()), wakeFrameIndex)
    }

    private fun runMoonshine(window: PcmWindow): AsrTiming {
        val initStart = SystemClock.elapsedRealtimeNanos(); val engine = SherpaMoonshineBenchmarkEngine(assets)
        val initMs = (SystemClock.elapsedRealtimeNanos() - initStart) / 1_000_000.0
        return try { engine.begin(window.samples); val text = engine.finish()?.text.orEmpty(); AsrTiming(initMs, engine.lastDecodeMs, engine.lastFinalizeMs, text) } finally { engine.close() }
    }

    private fun detectOnsetSample(pcm: ShortArray): Long? {
        val n = AudioEngine.FRAME_SAMPLES; val baselineFrames = minOf(20, pcm.size / n / 2)
        fun rms(offset: Int): Double { var sum = 0.0; for (i in offset until minOf(offset + n, pcm.size)) sum += pcm[i].toDouble() * pcm[i]; return sqrt(sum / n) }
        val threshold = maxOf(500.0, (0 until baselineFrames).map { rms(it * n) }.average() * 4.0); var consecutive = 0
        for (frame in baselineFrames until pcm.size / n) { consecutive = if (rms(frame * n) >= threshold) consecutive + 1 else 0; if (consecutive >= 2) return ((frame - 1) * n).toLong() }
        return null
    }

    private fun hasMoonshineAssets() = listOf("$MOONSHINE_ASSET_DIR/encoder_model.ort", "$MOONSHINE_ASSET_DIR/decoder_model_merged.ort", "$MOONSHINE_ASSET_DIR/tokens.txt").all { path -> try { assets.open(path).use { }; true } catch (_: Throwable) { false } }
    private fun saveSanityPcm(runId: String, pcm: ShortArray) { val bytes = ByteBuffer.allocate(pcm.size * 2).order(ByteOrder.LITTLE_ENDIAN); pcm.forEach { bytes.putShort(it) }; FileOutputStream(File(sanityDir(), "$runId.pcm16le")).use { it.write(bytes.array()) } }

    private fun sanityCounts(): Map<String, Int> {
        val counts = mutableMapOf<String, Int>()
        val manifest = File(sanityDir(), SANITY_JSONL)
        if (!manifest.exists()) return counts
        manifest.forEachLine(Charsets.UTF_8) { line ->
            try {
                val id = JSONObject(line).optString("phrase_id")
                if (id.isNotBlank()) counts[id] = (counts[id] ?: 0) + 1
            } catch (_: Throwable) {
                // Progress display is best-effort. The exported JSONL remains the source of truth.
            }
        }
        return counts
    }

    private fun sanityCount(id: String): Int = sanityCounts()[id] ?: 0

    private fun selectFirstIncompleteSanityPrompt(): Boolean {
        if (!::sanityMode.isInitialized || !sanityMode.isChecked) return false
        val counts = sanityCounts()
        val next = sanityPrompts.indexOfFirst { (counts[it.id] ?: 0) < SANITY_REPEATS_PER_PHRASE }
        if (next < 0) return false
        promptIndex = next
        return true
    }

    private fun resetSanityProgress() {
        val failed = sanityDir().listFiles()?.filterNot { it.deleteRecursively() }.orEmpty()
        if (failed.isNotEmpty()) {
            stateText.text = "FAILED · 일부 sanity 파일을 삭제하지 못했습니다"
            return
        }
        promptIndex = 0
        stateText.text = "RESET · Sanity 0/60"
        renderPrompt()
        renderStats()
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
        val prompt = activePrompts()[promptIndex]
        if (sanityMode.isChecked) {
            val completed = sanityCount(checkNotNull(prompt.id))
            val nextRepeat = minOf(completed + 1, SANITY_REPEATS_PER_PHRASE)
            promptText.text = "[${prompt.id}] 문장 ${promptIndex + 1}/${sanityPrompts.size} · 반복 $nextRepeat/$SANITY_REPEATS_PER_PHRASE\n“${prompt.text}”"
            recordButton.text = if (completed >= SANITY_REPEATS_PER_PHRASE) "이 문장 완료 · 5/5" else "녹음 $nextRepeat/$SANITY_REPEATS_PER_PHRASE"
        } else {
            promptText.text = "[${prompt.id ?: prompt.label.name}]\n“${prompt.text}”"
            recordButton.text = "3초 녹음 → 라벨 저장"
        }
    }

    private fun renderStats() {
        if (sanityMode.isChecked) {
            val counts = sanityCounts()
            val total = sanityPrompts.sumOf { counts[it.id] ?: 0 }
            statsText.text = buildString {
                append("Sanity progress: ").append(total).append('/').append(SANITY_TOTAL_RUNS).append("\n")
                sanityPrompts.forEach { prompt ->
                    append(prompt.id).append(": ").append(counts[prompt.id] ?: 0).append('/').append(SANITY_REPEATS_PER_PHRASE).append("\n")
                }
                append("저장 위치: ").append(sanityDir().absolutePath)
            }
            return
        }

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

    private fun datasetDir(): File = dataDir(DATASET_DIR)
    private fun sanityDir(): File = dataDir(SANITY_DIR)
    private fun dataDir(name: String): File { val root = getExternalFilesDir(name) ?: File(filesDir, name); check(root.exists() || root.mkdirs()) { "Unable to create $name" }; return root }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    private fun sha256(file: File): String { val digest = MessageDigest.getInstance("SHA-256"); file.inputStream().use { input -> val buffer = ByteArray(64 * 1024); while (true) { val read = input.read(buffer); if (read < 0) break; if (read > 0) digest.update(buffer, 0, read) } }; return digest.digest().joinToString("") { "%02x".format(it) } }

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
        private const val SANITY_CUE_DELAY_MS = 1_200L
        private const val SANITY_REPEATS_PER_PHRASE = 5
        private const val SANITY_TOTAL_RUNS = 12 * SANITY_REPEATS_PER_PHRASE
        private const val DATASET_DIR = "okja-physical-command-dataset"
        private const val MANIFEST_NAME = "manifest.jsonl"
        private const val SANITY_DIR = "okja-pipeline-sanity-v2"
        private const val SANITY_JSONL = "sanity-v2.jsonl"
        private const val PREFS_NAME = "okja-command-dataset"
        private const val PREF_SPEAKER_ID = "speaker-id"
        private const val PREF_CONDITION = "condition"
        private const val MOONSHINE_ASSET_DIR = "sherpa-onnx-moonshine-tiny-ko-quantized-2026-02-27"
    }
}
