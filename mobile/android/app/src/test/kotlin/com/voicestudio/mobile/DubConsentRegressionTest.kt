package com.voicestudio.mobile

import android.app.Application
import android.os.Looper
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.viewModelScope
import androidx.test.core.app.ApplicationProvider
import androidx.work.workDataOf
import androidx.work.testing.WorkManagerTestInitHelper
import com.voicestudio.mobile.data.*
import com.voicestudio.mobile.designsystem.*
import com.voicestudio.mobile.features.*
import com.voicestudio.mobile.features.dub.DubScreen
import com.voicestudio.mobile.l10n.L10n
import com.voicestudio.mobile.network.*
import kotlinx.coroutines.*
import okhttp3.mockwebserver.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[34])
class DubConsentRegressionTest {
    @get:Rule val compose=createComposeRule()
    private val engineBody="""{"active":"deepl","engines":[{"id":"deepl","display_name":"DeepL","category":"online","installed":true,"ready":true}]}"""
    @Test fun onlineServiceIsNamedAndDeclineNeverStartsDub() {
        val app=ApplicationProvider.getApplicationContext<Application>()
        WorkManagerTestInitHelper.initializeTestWorkManager(app)
        val store=SessionStore(app,object:CredentialVault {
            override fun read(host:String)=Secret()
            override fun write(host:String,secret:Secret?) {}
        })
        runBlocking {store.update {Preferences(consent=false)}}
        val paths=java.util.concurrent.CopyOnWriteArrayList<String>()
        val server=MockWebServer()
        server.dispatcher=object:okhttp3.mockwebserver.Dispatcher() {
            override fun dispatch(request:RecordedRequest):MockResponse {
                paths.add(request.path.orEmpty())
                return when(request.path) {
                    "/health" -> MockResponse().setHeader("x-omnivoice-backend","test").setBody("""{"status":"ok","version":"test"}""")
                    "/profiles","/history","/dub/history" -> MockResponse().setBody("[]")
                    "/engines" -> MockResponse().setBody("""{"tts":{"active":"test","backends":[]}}""")
                    "/engines/translation" -> MockResponse().setBody(engineBody)
                    else -> MockResponse().setResponseCode(500)
                }
            }
        };server.start()
        val vm=StudioViewModel(app,store)
        fun awaitIdle() = compose.waitUntil(15000) {
            shadowOf(Looper.getMainLooper()).idle()
            !vm.state.value.loading&&!vm.state.value.busy
        }
        try {
            awaitIdle();vm.connect(server.url("/").toString(),"","");awaitIdle()
            compose.setContent {CompositionLocalProvider(LocalL10n provides L10n.load(app,"en")) {VoiceStudioTheme {DubScreen(vm)}}}
            compose.onNodeWithText("Paste a link").performTextInput("https://example.test/video")
            compose.onNodeWithText("Target languages").performScrollTo().performClick()
            compose.onNodeWithText("Search").performTextInput("French")
            compose.onNode(hasText("French") and !hasSetTextAction()).performClick()
            compose.onNodeWithText("Close").performClick()
            compose.onNodeWithText("Voice").performScrollTo().performClick()
            compose.onNodeWithText("Default voice (engine preset)").performClick()
            repeat(2) {
                compose.onNodeWithText("Start dubbing").performScrollTo().performClick()
                awaitIdle()
                compose.onNodeWithText("Allow online translation for this dub?").assertExists()
                compose.onNodeWithText("Your computer will send this dub’s transcript to DeepL for translation. Allow this only for this job?").assertExists()
                assertFalse(paths.any {it.startsWith("/dub/translate") || it.startsWith("/dub/ingest-url")})
                compose.onNodeWithText("Do not translate").performClick()
                compose.onAllNodes(isDialog()).assertCountEquals(0)
                assertFalse(paths.any {it.startsWith("/dub/translate") || it.startsWith("/dub/ingest-url")})
            }
            assertEquals(2,paths.count {it=="/engines/translation"})
        } finally {vm.viewModelScope.cancel();server.shutdown()}
    }
    @Test fun durableWorkerRequiresApprovalAndRejectsProviderChanges()=runBlocking {
        val server=MockWebServer();server.start()
        val api=VoiceStudioApi(PairingAddress.parse(server.url("/").toString()))
        try {
            val unapproved=workDataOf("translation_provider" to "deepl","translation_category" to "online")
            server.enqueue(MockResponse().setBody(engineBody))
            try {DubWorker.authorizedTranslation(api,unapproved);fail("Approval required")} catch(e:ClientFailure) {assertEquals("mobile.dub.translation_setup",e.key)}
            assertEquals("/engines/translation",server.takeRequest().path)
            val approved=workDataOf("translation_provider" to "deepl","translation_category" to "online","translation_confirmed" to true)
            server.enqueue(MockResponse().setBody(engineBody))
            val authorization=DubWorker.authorizedTranslation(api,approved)
            assertEquals("deepl",authorization.provider);assertTrue(authorization.onlineConfirmed)
            server.takeRequest()
            server.enqueue(MockResponse().setBody("""{"active":"google","engines":[{"id":"google","category":"online","installed":true,"ready":true}]}"""))
            try {DubWorker.authorizedTranslation(api,approved);fail("Changed provider must not reuse consent")} catch(e:ClientFailure) {assertEquals("mobile.dub.translation_changed",e.key)}
            server.takeRequest()
            assertEquals(3,server.requestCount)
        } finally {server.shutdown()}
    }
}
