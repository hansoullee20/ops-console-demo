package com.soul.aihub

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.os.SystemClock
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.soul.aihub.voice.AsrBenchmarkHarness
import com.soul.aihub.voice.AsrBenchmarkResult
import com.soul.aihub.voice.AudioEngine
import com.soul.aihub.voice.Pcm16UtteranceBuffer
import com.soul.aihub.voice.PcmContinuityTracker
import com.soul.aihub.voice.RecordedPcmCase
import com.soul.aihub.voice.SherpaMoonshineBenchmarkEngine
import com.soul.aihub.voice.SherpaStreamingAsrEngine
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
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Fold4 diagnostic runner for comparing local ASR engines against one captured PCM case.
 *
 * Capture is owned exclusively by [AudioEngine]. Recording is stopped before either ASR
 * engine is created, so both recognizers receive the exact same saved PCM and neither
 * recognizer can acquire the microphone.
 */
class LocalAsrBenchmarkActivity : Activity() {
    private data class Phrase(val text: String, val suffix: String)

    private val phrases = listOf(
        Phrase("옥자야 뭐하니", "뭐하니"),
        Phrase("옥자 TV 켜줘", "TV 켜줘"),
        Phrase("옥자 에어컨 꺼줘", "에어컨 꺼줘"),
    )

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val running = AtomicBoolean(false)
    private var phraseIndex = 0
    private var activeAudio: AudioEngine? = null

    private lateinit var phraseText: TextView
    private lateinit var stateText: TextView
    private lateinit var resultText: TextView
    private lateinit var recordButton: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        buildUi()
        renderPhrase()
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
        root.addView(text("옥자 · Same-PCM ASR Benchmark", 25f, Color.WHITE))
        root.addView(text("Moonshine tiny-ko → Zipformer smoke · 동일 PCM", 14f, Color.LTGRAY))

        phraseText = text("", 23f, Color.WHITE)
        stateText = text("READY", 17f, Color.rgb(180, 220, 255))
        resultText = text("", 14f, Color.LTGRAY).apply { gravity = Gravity.START }
        root.addView(phraseText)
        root.addView(stateText)

        val next = button("다음 문구")
        next.setOnClickListener {
            if (!running.get()) {
                phraseIndex = (phraseIndex + 1) % phrases.size
                renderPhrase()
            }
        }
        root.addView(next)

        recordButton = button("4초 녹음 → 동일 PCM 비교")
        recordButton.setOnClickListener { startBenchmark() }
        root.addView(recordButton)
        root.addView(resultText)
        setContentView(root)
    }

    private fun startBenchmark() {
        if (!running.compareAndSet(false, true)) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            running.set(false)
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_AUDIO)
            return
        }

        recordButton.isEnabled = false
        resultText.text = ""
        val phrase = phrases[phraseIndex]
        scope.launch {
            try {
                stateText.text = "준비… 0.8초 뒤 말하세요"
                delay(800)
                stateText.text = "지금 말하세요 · 4초 녹음"
                val pcm = captureFourSeconds()
                val corpusFile = savePcm(pcm, phrase)
                stateText.text = "동일 PCM 로컬 ASR 실행 중…"

                val results = withContext(Dispatchers.Default) {
                    runSamePcm(pcm, phrase)
                }
                val resultFile = saveResults(corpusFile, phrase, results)
                renderResults(results, corpusFile, resultFile)
                stateText.text = "DONE · 같은 PCM 비교 완료"
            } catch (t: Throwable) {
                stateText.text = "FAILED"
                resultText.text = "${t.javaClass.simpleName}: ${t.message ?: "unknown"}"
            } finally {
                activeAudio?.close()
                activeAudio = null
                running.set(false)
                recordButton.isEnabled = true
            }
        }
    }

    private suspend fun captureFourSeconds(): ShortArray {
        val targetSamples = AudioEngine.SAMPLE_RATE_HZ * RECORD_SECONDS
        val buffer = Pcm16UtteranceBuffer(maxSamples = AudioEngine.SAMPLE_RATE_HZ * 5)
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
                        "PCM capture discontinuity: expected sequence=${observation.expectedSequence}, " +
                            "actual=${observation.actualSequence}, missingFrames=${observation.missingFrames}, " +
                            "missingSamples=${observation.missingSamples}"
                    }
                    buffer.append(frame.samples)
                }
        }

        try {
            check(audio.start()) { "AudioEngine did not start" }
            withTimeout(6_000) { collector.await() }
        } finally {
            audio.stop()
            collector.cancel()
        }
        return buffer.snapshot()
    }

    private fun runSamePcm(pcm: ShortArray, phrase: Phrase): List<EngineOutcome> {
        val recorded = RecordedPcmCase(
            id = "fold4-${System.currentTimeMillis()}",
            pcm16 = pcm,
            expectedTranscript = phrase.text,
            expectedCommandSuffix = phrase.suffix,
        )
        val harness = AsrBenchmarkHarness()
        val outcomes = mutableListOf<EngineOutcome>()

        outcomes += runEngine("moonshine-tiny-ko") {
            SherpaMoonshineBenchmarkEngine(assets)
        }.invoke(harness, recorded)

        outcomes += runEngine("zipformer-ko-smoke") {
            SherpaStreamingAsrEngine(assets)
        }.invoke(harness, recorded)

        return outcomes
    }

    private fun runEngine(
        name: String,
        factory: () -> com.soul.aihub.voice.StreamingAsrEngine,
    ): (AsrBenchmarkHarness, RecordedPcmCase) -> EngineOutcome = { harness, recorded ->
        try {
            val replayStartNs = SystemClock.elapsedRealtimeNanos()
            val beforeNs = SystemClock.elapsedRealtimeNanos()
            val result = harness.run(
                case = recorded,
                engineName = name,
                engine = factory(),
                captureStartElapsedRealtimeNs = replayStartNs,
            )
            val processingMs = (SystemClock.elapsedRealtimeNanos() - beforeNs) / 1_000_000L
            EngineOutcome(name = name, result = result, processingMs = processingMs, error = null)
        } catch (t: Throwable) {
            EngineOutcome(name = name, result = null, processingMs = null,
                error = "${t.javaClass.simpleName}: ${t.message ?: "unknown"}")
        }
    }

    private fun savePcm(pcm: ShortArray, phrase: Phrase): File {
        val root = benchmarkDir()
        val file = File(root, "${System.currentTimeMillis()}-${phraseIndex}.pcm16le")
        val bytes = ByteBuffer.allocate(pcm.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        pcm.forEach { bytes.putShort(it) }
        FileOutputStream(file).use { it.write(bytes.array()) }
        return file
    }

    private fun saveResults(
        pcmFile: File,
        phrase: Phrase,
        outcomes: List<EngineOutcome>,
    ): File {
        val root = JSONObject()
        root.put("schema", "okja.asr-benchmark.v1")
        root.put("created_at_ms", System.currentTimeMillis())
        root.put("phrase", phrase.text)
        root.put("expected_suffix", phrase.suffix)
        root.put("pcm_file", pcmFile.name)
        root.put("sample_rate_hz", AudioEngine.SAMPLE_RATE_HZ)
        root.put("pcm_samples", pcmFile.length() / 2)
        outcomes.forEach { outcome ->
            val value = JSONObject()
            value.put("processing_ms", outcome.processingMs ?: JSONObject.NULL)
            value.put("error", outcome.error ?: JSONObject.NULL)
            outcome.result?.let { r ->
                value.put("transcript", r.finalTranscript)
                value.put("transcript_exact", r.transcriptMatchesExpected)
                value.put("suffix_preserved", r.commandSuffixPreserved)
                value.put("first_partial_replay_ms", r.firstPartialLatencyMs ?: JSONObject.NULL)
                value.put("final_replay_ms", r.finalLatencyMs ?: JSONObject.NULL)
                value.put("pcm_discontinuity", r.discontinuityDetected)
                value.put("recognition_expected_but_empty", r.recognitionExpectedButEmpty)
                value.put("update_count", r.updateCount)
            }
            root.put(outcome.name, value)
        }

        val file = File(benchmarkDir(), pcmFile.nameWithoutExtension + ".json")
        file.writeText(root.toString(2), Charsets.UTF_8)
        return file
    }

    private fun renderResults(outcomes: List<EngineOutcome>, pcm: File, json: File) {
        val text = buildString {
            outcomes.forEach { outcome ->
                append(outcome.name).append("\n")
                if (outcome.error != null) {
                    append("  ERROR: ").append(outcome.error).append("\n")
                } else {
                    val r = outcome.result!!
                    append("  transcript: ").append(r.finalTranscript.ifBlank { "<EMPTY>" }).append("\n")
                    append("  suffix: ").append(r.commandSuffixPreserved).append("\n")
                    append("  silent-failure: ").append(r.recognitionExpectedButEmpty).append("\n")
                    append("  processing: ").append(outcome.processingMs).append(" ms\n")
                }
            }
            append("\nSaved: ").append(pcm.name).append("\n").append(json.name)
        }
        resultText.text = text
    }

    private fun benchmarkDir(): File {
        val root = getExternalFilesDir("okja-asr-benchmark") ?: File(filesDir, "okja-asr-benchmark")
        check(root.exists() || root.mkdirs()) { "Unable to create benchmark directory" }
        return root
    }

    private fun renderPhrase() {
        phraseText.text = "말할 문구: “${phrases[phraseIndex].text}”"
        resultText.text = "한 번 녹음한 PCM을 두 로컬 엔진에 그대로 재생합니다."
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
        activeAudio?.close()
        activeAudio = null
        scope.cancel()
        super.onDestroy()
    }

    data class EngineOutcome(
        val name: String,
        val result: AsrBenchmarkResult?,
        val processingMs: Long?,
        val error: String?,
    )

    companion object {
        private const val REQ_AUDIO = 3101
        private const val RECORD_SECONDS = 4
    }
}
