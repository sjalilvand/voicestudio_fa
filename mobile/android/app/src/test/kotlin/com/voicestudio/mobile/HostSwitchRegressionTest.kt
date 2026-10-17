package com.voicestudio.mobile

import android.app.Application
import android.os.Looper
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.media3.common.Player
import androidx.lifecycle.viewModelScope
import androidx.work.*
import androidx.work.testing.WorkManagerTestInitHelper
import com.voicestudio.mobile.features.LocalHostPlayerFactory
import org.mockito.Mockito.*
import androidx.test.core.app.ApplicationProvider
import com.voicestudio.mobile.data.*
import com.voicestudio.mobile.features.StudioViewModel
import kotlinx.coroutines.*
import okhttp3.mockwebserver.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[34])
class HostSwitchRegressionTest {
    @get:Rule val compose=createComposeRule()
    private lateinit var vm: StudioViewModel
    private lateinit var a: MockWebServer
    private lateinit var b: MockWebServer
    private suspend fun awaitIdle() {
        withTimeout(15000) {
            do { shadowOf(Looper.getMainLooper()).idle(); delay(10) } while(vm.state.value.loading || vm.state.value.busy)
        }
    }
    @Before fun setup() = runBlocking {
        val app=ApplicationProvider.getApplicationContext<Application>()
        WorkManagerTestInitHelper.initializeTestWorkManager(app)
        val store=SessionStore(app,object:CredentialVault {
            private val secrets=mutableMapOf<String,Secret>()
            override fun read(host:String)=secrets[host]
            override fun write(host:String,secret:Secret?) { if(secret==null) secrets.remove(host) else secrets[host]=secret }
        })
        store.update {Preferences(consent=false)}
        fun server(id:String)=MockWebServer().apply {
            dispatcher=object:okhttp3.mockwebserver.Dispatcher() {
                override fun dispatch(request:RecordedRequest):MockResponse = when(request.path) {
                    "/health" -> MockResponse().setHeader("x-omnivoice-backend","test").setBody("""{"status":"ok","version":"test"}""")
                    "/profiles" -> MockResponse().setBody("""[{"id":"$id","name":"$id"}]""")
                    "/engines" -> MockResponse().setBody("""{"tts":{"active":"$id","backends":[{"id":"$id"}]}}""")
                    "/history" -> MockResponse().setBody("""[{"id":"$id","audio_path":"$id.wav"}]""")
                    "/dub/history" -> MockResponse().setBody("""[{"id":"$id","job_id":"$id"}]""")
                    "/api/auth/session" -> MockResponse().setResponseCode(204)
                    "/generate" -> MockResponse().setHeader("X-Audio-Id",id).setHeader("X-Audio-Path","$id.wav").setBody("RIFF")
                    else -> MockResponse().setResponseCode(404)
                }
            }; start()
        }
        a=server("host-a"); b=server("host-b")
        vm=StudioViewModel(app,store);awaitIdle()
    }
    @After fun teardown() {vm.viewModelScope.cancel(); a.shutdown(); b.shutdown()}
    @Test fun generatedAudioCannotMoveToAnotherHost() = runBlocking {
        vm.connect(a.url("/").toString(),"","");awaitIdle()
        vm.generate("Test","","host-a","Auto");awaitIdle()
        assertEquals("/audio/host-a.wav",vm.state.value.audio)
        vm.connect(b.url("/").toString(),"","");awaitIdle()
        assertNull("Host A audio must never be played or shared on host B",vm.state.value.audio)
        assertEquals(listOf("host-b"),vm.state.value.profiles.map {it.id})
        assertEquals(listOf("host-b"),vm.state.value.history.map {it.id})
        assertEquals(listOf("host-b"),vm.state.value.dubHistory.map {it.id})
        assertEquals("host-b",vm.state.value.engines.active)
        var request=b.takeRequest(10,TimeUnit.MILLISECONDS)
        while(request!=null) {assertFalse(request.path.orEmpty().contains("host-a"));request=b.takeRequest(10,TimeUnit.MILLISECONDS)}
    }
    @Test fun reconnectAndDisconnectClearCheckpointsAndStopOldMonitoring() = runBlocking {
        vm.connect(a.url("/").toString(),"","");awaitIdle()
        val oldHost=a.url("/").toString()
        val job="host-a-job"
        vm.store.checkpoint(oldHost,job,DubCheckpoint(uploaded=true,renderTask="render-a"))
        assertEquals("render-a",vm.store.checkpoint(oldHost,job).renderTask)
        val work=OneTimeWorkRequestBuilder<DubWorker>()
            .setInitialDelay(1,TimeUnit.DAYS).addTag(oldHost).addTag(DubWorker.TAG).build()
        val manager=WorkManager.getInstance(ApplicationProvider.getApplicationContext())
        withContext(Dispatchers.IO) {manager.enqueue(work).result.get()}
        vm.generate("Test","","host-a","Auto");awaitIdle()
        vm.reconnect(SavedHost(oldHost,"A",0));awaitIdle()
        assertEquals("render-a",vm.store.checkpoint(oldHost,job).renderTask)
        assertEquals(WorkInfo.State.ENQUEUED,withContext(Dispatchers.IO) {manager.getWorkInfoById(work.id).get()}?.state)
        vm.reconnect(SavedHost(b.url("/").toString(),"B",0));awaitIdle()
        assertNull(vm.state.value.audio)
        assertEquals("",vm.store.checkpoint(oldHost,job).renderTask)
        assertEquals(WorkInfo.State.CANCELLED,withContext(Dispatchers.IO) {manager.getWorkInfoById(work.id).get()}?.state)
        // A late write from a cancelled worker cannot restore A's checkpoint.
        vm.store.checkpoint(oldHost,job,DubCheckpoint(renderTask="stale-a"))
        assertEquals("",vm.store.checkpoint(oldHost,job).renderTask)
        val currentHost=b.url("/").toString()
        vm.store.checkpoint(currentHost,"job",DubCheckpoint(renderTask="render-b"))
        vm.disconnect();awaitIdle()
        val state=vm.state.value
        assertFalse(state.connected);assertNull(state.hostUrl);assertNull(state.audio)
        assertTrue(state.profiles.isEmpty());assertTrue(state.history.isEmpty());assertTrue(state.dubHistory.isEmpty())
        assertTrue(state.engines.backends.isEmpty())
        assertEquals("",vm.store.checkpoint(currentHost,"job").renderTask)
    }
    @Test fun switchingHostDisposesPlayerAndSavedSpeakForm() = runBlocking {
        vm.connect(a.url("/").toString(),"","");awaitIdle()
        vm.generate("Test","","host-a","Auto");awaitIdle()
        val player=mock(Player::class.java)
        `when`(player.duration).thenReturn(1000)
        compose.setContent {CompositionLocalProvider(LocalHostPlayerFactory provides {_,_->player}) {StudioApp(vm)}}
        compose.onNodeWithText("Type what you want to hear…").performTextInput("Text for A")
        compose.onAllNodesWithContentDescription("Play").assertCountEquals(2)
        val oldConnection=vm.state.value.connectionId
        vm.connect(b.url("/").toString(),"","");awaitIdle()
        compose.waitForIdle()
        assertTrue(vm.state.value.connectionId>oldConnection)
        verify(player).release()
        compose.onNodeWithText("Generated audio").assertDoesNotExist()
        compose.onNodeWithText("Text for A").assertDoesNotExist()
        compose.onAllNodesWithContentDescription("Play").assertCountEquals(1)
        assertNull(vm.state.value.audio)
    }

}
