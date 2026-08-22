package com.soul.aihub.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class GitBlobIntegrityTest {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun computesGitBlobIdentityNotPlainFileSha() {
        val file = temporaryFolder.newFile("sample.bin")
        file.writeBytes("test\n".toByteArray())

        assertEquals(
            "9daeafb9864cf43055ae93beb0afd6c7d144bfa4",
            GitBlobIntegrity.gitBlobSha1(file),
        )
        assertTrue(
            GitBlobIntegrity.matches(
                file,
                "9daeafb9864cf43055ae93beb0afd6c7d144bfa4",
            ),
        )
        assertFalse(
            GitBlobIntegrity.matches(
                file,
                "0000000000000000000000000000000000000000",
            ),
        )
    }
}
