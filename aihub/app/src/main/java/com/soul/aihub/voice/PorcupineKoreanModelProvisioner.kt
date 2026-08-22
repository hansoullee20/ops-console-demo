package com.soul.aihub.voice

import android.content.Context
import ai.picovoice.porcupine.Porcupine
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.security.MessageDigest

/** Paths for one provisioned Korean Porcupine wake configuration. */
data class PorcupineProvisionedModels(
    val keywordPath: String,
    val modelPath: String,
    val phrase: String,
    val language: String,
)

/**
 * One-time network provisioning for Korean Porcupine assets.
 *
 * Inference remains fully local after this completes. The Picovoice AccessKey is used only as an
 * input to provisioning/engine creation and is never persisted by this class.
 *
 * The Korean `.pv` parameter file is pinned to a specific upstream Picovoice repository commit and
 * Git blob SHA. The custom Android `.ppn` for `옥자야` is trained with Porcupine's official
 * `trainWakeWordFromPhrase()` API and cached in app-private storage.
 */
class PorcupineKoreanModelProvisioner(
    context: Context,
) {
    private val appContext = context.applicationContext

    suspend fun provision(
        accessKey: String,
        phrase: String = DEFAULT_PHRASE,
        forceRetrainKeyword: Boolean = false,
    ): PorcupineProvisionedModels = withContext(Dispatchers.IO) {
        require(accessKey.isNotBlank()) { "Picovoice AccessKey must not be blank" }
        require(phrase.isNotBlank()) { "wake phrase must not be blank" }

        val root = File(appContext.filesDir, CACHE_DIR)
        check(root.exists() || root.mkdirs()) { "unable to create Porcupine model directory" }

        val modelFile = File(root, KOREAN_MODEL_FILENAME)
        ensurePinnedKoreanModel(modelFile)

        val keywordFile = File(root, keywordFilename(phrase))
        if (forceRetrainKeyword || !keywordFile.isFile || keywordFile.length() <= 0L) {
            trainKeywordAtomically(accessKey, phrase, keywordFile)
        }

        check(keywordFile.isFile && keywordFile.length() > 0L) {
            "Porcupine keyword provisioning produced no model"
        }

        PorcupineProvisionedModels(
            keywordPath = keywordFile.absolutePath,
            modelPath = modelFile.absolutePath,
            phrase = phrase,
            language = LANGUAGE_KO,
        )
    }

    private fun ensurePinnedKoreanModel(destination: File) {
        if (destination.isFile && GitBlobIntegrity.matches(destination, KOREAN_MODEL_GIT_BLOB_SHA1)) {
            return
        }

        destination.delete()
        val temporary = File(destination.parentFile, destination.name + ".download")
        temporary.delete()
        try {
            downloadPinnedModel(temporary)
            check(GitBlobIntegrity.matches(temporary, KOREAN_MODEL_GIT_BLOB_SHA1)) {
                "downloaded Korean Porcupine model failed pinned Git blob verification"
            }
            replaceAtomically(temporary, destination)
        } finally {
            temporary.delete()
        }
    }

    private fun downloadPinnedModel(destination: File) {
        val connection = (URL(KOREAN_MODEL_URL).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 15_000
            readTimeout = 30_000
            instanceFollowRedirects = true
            useCaches = false
        }

        try {
            val code = connection.responseCode
            check(code in 200..299) { "Korean Porcupine model download failed: HTTP $code" }
            val declared = connection.contentLengthLong
            if (declared > 0L) {
                check(declared <= MAX_MODEL_BYTES) { "Porcupine model exceeds size limit: $declared" }
            }

            connection.inputStream.use { input ->
                FileOutputStream(destination).use { output ->
                    val buffer = ByteArray(32 * 1024)
                    var total = 0L
                    while (true) {
                        val read = input.read(buffer)
                        if (read < 0) break
                        total += read.toLong()
                        check(total <= MAX_MODEL_BYTES) { "Porcupine model download exceeds size limit" }
                        output.write(buffer, 0, read)
                    }
                    output.fd.sync()
                }
            }
            check(destination.length() > 0L) { "downloaded Korean Porcupine model is empty" }
        } finally {
            connection.disconnect()
        }
    }

    private fun trainKeywordAtomically(accessKey: String, phrase: String, destination: File) {
        val temporary = File(destination.parentFile, destination.name + ".pending.ppn")
        temporary.delete()
        try {
            Porcupine.trainWakeWordFromPhrase(
                accessKey,
                temporary.absolutePath,
                LANGUAGE_KO,
                phrase,
            )
            check(temporary.isFile && temporary.length() > 0L) {
                "Porcupine keyword training produced no model"
            }
            replaceAtomically(temporary, destination)
        } finally {
            temporary.delete()
        }
    }

    private fun replaceAtomically(source: File, destination: File) {
        destination.delete()
        if (!source.renameTo(destination)) {
            FileInputStream(source).use { input ->
                FileOutputStream(destination).use { output ->
                    input.copyTo(output)
                    output.fd.sync()
                }
            }
            source.delete()
        }
        check(destination.isFile && destination.length() > 0L) {
            "failed to install provisioned Porcupine model ${destination.name}"
        }
    }

    private fun keywordFilename(phrase: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(phrase.toByteArray(StandardCharsets.UTF_8))
            .take(8)
            .joinToString("") { "%02x".format(it) }
        return "okja-$LANGUAGE_KO-$digest-android.ppn"
    }

    companion object {
        const val DEFAULT_PHRASE = "옥자야"
        const val LANGUAGE_KO = "ko"

        private const val CACHE_DIR = "porcupine-4.0.2-ko"
        private const val KOREAN_MODEL_FILENAME = "porcupine_params_ko.pv"
        private const val MAX_MODEL_BYTES = 2L * 1024L * 1024L

        // Picovoice/porcupine master as observed 2026-08-22. Pinning prevents a mutable-master
        // download from silently changing the acoustic parameter model under an Okja benchmark.
        const val KOREAN_MODEL_UPSTREAM_COMMIT = "b42ec9f849c05bb2aa99e6cbd1c85c9b66e103bb"
        const val KOREAN_MODEL_GIT_BLOB_SHA1 = "3e9b62e31fe59481d52d74e45415d62eb52e23e9"
        const val KOREAN_MODEL_URL =
            "https://raw.githubusercontent.com/Picovoice/porcupine/" +
                KOREAN_MODEL_UPSTREAM_COMMIT +
                "/lib/common/porcupine_params_ko.pv"
    }
}

/** Git's SHA-1 object identity: SHA1("blob <size>\\0" + bytes). */
internal object GitBlobIntegrity {
    fun matches(file: File, expectedHexSha1: String): Boolean {
        if (!file.isFile || file.length() <= 0L) return false
        return try {
            gitBlobSha1(file).equals(expectedHexSha1, ignoreCase = true)
        } catch (_: Throwable) {
            false
        }
    }

    fun gitBlobSha1(file: File): String {
        require(file.isFile) { "file does not exist: ${file.absolutePath}" }
        val digest = MessageDigest.getInstance("SHA-1")
        val header = "blob ${file.length()}\u0000".toByteArray(StandardCharsets.UTF_8)
        digest.update(header)
        FileInputStream(file).use { input ->
            val buffer = ByteArray(32 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
