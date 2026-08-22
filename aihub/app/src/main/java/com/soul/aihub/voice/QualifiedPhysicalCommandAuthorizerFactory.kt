package com.soul.aihub.voice

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/**
 * Loads only a model installed by `command_classifier/install_qualified_classifier.py`.
 *
 * Missing/tampered/mismatched assets do not produce an authorizer. Callers should use
 * [createOrRejecting] so physical control remains fail-closed instead of attempting a candidate
 * model or hand-entered thresholds.
 */
object QualifiedPhysicalCommandAuthorizerFactory {
    private const val ASSET_DIR = "okja-physical-command"
    private const val MANIFEST_ASSET = "$ASSET_DIR/qualified-manifest.json"
    private const val EXPECTED_SCHEMA = "okja.physical-command-qualified.v1"
    private const val EXPECTED_MODEL_FILE = "physical-command.tflite"

    suspend fun createOrRejecting(context: Context): PhysicalCommandAuthorizer {
        return try {
            create(context)
        } catch (_: Throwable) {
            RejectingPhysicalCommandAuthorizer
        }
    }

    suspend fun create(context: Context): TflitePhysicalCommandAuthorizer = withContext(Dispatchers.IO) {
        val appContext = context.applicationContext
        val manifest = appContext.assets.open(MANIFEST_ASSET).bufferedReader(Charsets.UTF_8).use {
            JSONObject(it.readText())
        }

        check(manifest.getString("schema") == EXPECTED_SCHEMA) {
            "unexpected physical-command manifest schema"
        }
        check(manifest.optBoolean("deployment_allowed", false)) {
            "physical-command manifest is not deployment-qualified"
        }
        requireExactClassOrder(manifest.getJSONArray("class_order"))

        val modelFile = manifest.getString("model_file")
        check(modelFile == EXPECTED_MODEL_FILE) {
            "physical-command model filename must be $EXPECTED_MODEL_FILE"
        }
        val modelAsset = "$ASSET_DIR/$modelFile"
        val expectedSha256 = manifest.getString("model_sha256").lowercase()
        check(expectedSha256.matches(Regex("[0-9a-f]{64}"))) {
            "invalid physical-command model SHA-256"
        }
        val actualSha256 = sha256Asset(appContext, modelAsset)
        check(actualSha256 == expectedSha256) {
            "physical-command model SHA-256 mismatch"
        }

        val thresholds = PhysicalCommandThresholds(
            minConfidence = manifest.getDouble("min_confidence").toFloat(),
            minTopTwoMargin = manifest.getDouble("min_top_two_margin").toFloat(),
            minOppositeActionMargin = manifest.getDouble("min_opposite_action_margin").toFloat(),
        )

        TflitePhysicalCommandAuthorizer.createFromAsset(
            context = appContext,
            assetName = modelAsset,
            thresholds = thresholds,
        )
    }

    private fun requireExactClassOrder(array: JSONArray) {
        val expected = PhysicalCommandScorePolicy.CLASS_ORDER.map { it.name }
        check(array.length() == expected.size) { "physical-command class count mismatch" }
        expected.indices.forEach { index ->
            check(array.getString(index) == expected[index]) {
                "physical-command class order mismatch at index $index"
            }
        }
    }

    private fun sha256Asset(context: Context, assetName: String): String {
        val digest = MessageDigest.getInstance("SHA-256")
        context.assets.open(assetName).use { input ->
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
