package com.soul.aihub.voice

/** Process-memory handoff for diagnostic Activities. Never persisted or committed. */
object PorcupineSessionAccessKey {
    @Volatile
    private var value: String? = null

    fun remember(accessKey: String) {
        require(accessKey.isNotBlank()) { "AccessKey must not be blank" }
        value = accessKey
    }

    fun current(): String? = value
}
