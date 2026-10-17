package com.voicestudio.mobile.features.dictate

import com.voicestudio.mobile.network.*
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.mockwebserver.*
import org.junit.Test
import org.junit.Assert.*

class DictationProtocolTest {
    private suspend fun awaitCondition(condition: () -> Boolean) {
        withTimeout(2000) { while(!condition()) delay(5) }
    }
    @Test fun utteranceFinalsKeepRecordingUntilSummaryWithoutSocketClose() = runBlocking {
        val server=MockWebServer()
        val opened=CompletableDeferred<WebSocket>()
        server.enqueue(MockResponse().setBody("""{"ready":true}"""))
        server.enqueue(MockResponse().withWebSocketUpgrade(object:WebSocketListener() {
            override fun onOpen(webSocket:WebSocket,response:Response) {opened.complete(webSocket)}
            override fun onClosing(webSocket:WebSocket,code:Int,reason:String) {webSocket.close(code,null)}
        }))
        server.start()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val errors=java.util.concurrent.CopyOnWriteArrayList<Throwable>()
        val captureCycles=java.util.concurrent.atomic.AtomicInteger()
        val controller=DictationController(VoiceStudioApi(PairingAddress.parse(server.url("/").toString())),scope,{errors.add(it)},
            DictationAudioSource {keepRecording,_ -> while(keepRecording()) {captureCycles.incrementAndGet();delay(5)}})
        try {
            controller.start()
            val socket=withTimeout(2000) {opened.await()}
            socket.send("""{"type":"partial","text":"First"}""")
            awaitCondition {controller.text.value=="First"}
            socket.send("""{"type":"final","text":"First phrase.","final_kind":"utterance"}""")
            awaitCondition {controller.text.value=="First phrase."}
            assertTrue(controller.active.value)
            socket.send("""{"type":"final","text":"Ignore this","final_kind":"unknown"}""")
            socket.send("""{"type":"final","text":"","final_kind":"utterance"}""")
            socket.send("""{"type":"partial","text":"Second"}""")
            awaitCondition {controller.text.value=="First phrase. Second"}
            socket.send("""{"type":"final","text":"Second phrase.","final_kind":"utterance"}""")
            awaitCondition {controller.text.value=="First phrase. Second phrase."}
            val cycles=captureCycles.get()
            awaitCondition {captureCycles.get()>=cycles+2}
            assertTrue(controller.active.value)
            socket.send("""{"type":"final","text":"First phrase. Second phrase.","final_kind":"summary","refined_text":"First phrase; second phrase."}""")
            awaitCondition {!controller.active.value}
            assertEquals("First phrase; second phrase.",controller.text.value)
            assertTrue(errors.toString(),errors.isEmpty())
        } finally {controller.close();scope.cancel();server.shutdown()}
    }
    @Test fun emptySummaryAndLegacyEofPreserveCommittedText() = runBlocking {
        for(summary in listOf("""{"type":"final","text":"","final_kind":"summary"}""",
            """{"type":"final","text":"Whole session.","final_kind":"summary"}""", """{"type":"final","text":"Whole session."}""")) {
            val server=MockWebServer()
            val opened=CompletableDeferred<WebSocket>()
            val eof=CompletableDeferred<Unit>()
            server.enqueue(MockResponse().setBody("""{"ready":true}"""))
            server.enqueue(MockResponse().withWebSocketUpgrade(object:WebSocketListener() {
                override fun onOpen(webSocket:WebSocket,response:Response) {opened.complete(webSocket)}
                override fun onMessage(webSocket:WebSocket,text:String) {if(text.contains("input_audio.end")) eof.complete(Unit)}
                override fun onClosing(webSocket:WebSocket,code:Int,reason:String) {webSocket.close(code,null)}
            }))
            server.start()
            val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
            val controller=DictationController(VoiceStudioApi(PairingAddress.parse(server.url("/").toString())),scope,{},
                DictationAudioSource {keepRecording,_ -> while(keepRecording()) delay(5)})
            try {
                controller.start()
                val socket=withTimeout(2000) {opened.await()}
                socket.send("""{"type":"final","text":"Whole session.","final_kind":"utterance"}""")
                awaitCondition {controller.text.value=="Whole session."}
                controller.finish()
                withTimeout(2000) {eof.await()}
                socket.send(summary)
                awaitCondition {!controller.active.value}
                assertEquals("Whole session.",controller.text.value)
            } finally {controller.close();scope.cancel();server.shutdown()}
        }
    }
}
