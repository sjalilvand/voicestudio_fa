package com.voicestudio.mobile.network

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import okhttp3.mockwebserver.*
import org.junit.*
import org.junit.Assert.*

class TranslationPolicyTest {
    private val json=Json {ignoreUnknownKeys=true}
    @Test fun activeEngineMustExistBeInstalledAndReady() {
        for(body in listOf(
            """{"active":"missing","engines":[]}""",
            """{"active":"argos","engines":[{"id":"argos","category":"offline","installed":false,"ready":true}]}""",
            """{"active":"argos","engines":[{"id":"argos","category":"offline","installed":true,"ready":false}]}""",
            """{"active":"argos","engines":[{"id":"argos"}]}"""
        )) {
            val error=assertThrows(ClientFailure::class.java) {json.decodeFromString<TranslationEngines>(body).activeEngine()}
            assertEquals("mobile.dub.translation_setup",error.key)
        }
    }
    @Test fun onlineConsentIsPerJobAndDecliningNeverTranslates()=runBlocking {
        val server=MockWebServer();server.start()
        try {
            val api=VoiceStudioApi(PairingAddress.parse(server.url("/").toString()))
            val body="""{"active":"deepl","engines":[{"id":"argos","category":"offline","installed":true,"ready":true},{"id":"deepl","display_name":"DeepL","category":"online","installed":true,"ready":true}]}"""
            server.enqueue(MockResponse().setBody(body))
            val engine=api.translationEngine()
            assertEquals("deepl",engine.id);assertEquals("DeepL",engine.displayName)
            assertEquals("/engines/translation",server.takeRequest().path)
            assertNull(engine.authorize())
            assertNull(engine.authorize(false))
            assertEquals(1,server.requestCount)
            val approval=engine.authorize(true)!!
            assertTrue(approval.onlineConfirmed)
            server.enqueue(MockResponse().setBody("""{"translated":[{"id":"0","text":"Bonjour"}]}"""))
            api.translate("j","fr","en",listOf(Segment(start=0.0,end=1.0,text="Hello")),approval)
            val request=server.takeRequest()
            assertEquals("/dub/translate",request.path)
            assertEquals("deepl",json.parseToJsonElement(request.body.readUtf8()).jsonObject["provider"]!!.jsonPrimitive.content)
            assertNull("A previous approval must not carry into another job",engine.authorize())
        } finally {server.shutdown()}
    }
    @Test fun dubVoiceIsPresetOrExplicitProfileAndNeverImplicitSourceCloning()=runBlocking {
        val server=MockWebServer();server.start()
        try {
            val api=VoiceStudioApi(PairingAddress.parse(server.url("/").toString()))
            try {
                api.startDub("job","fr","French",DubVoiceChoice.UNSELECTED,listOf(Segment(start=0.0,end=1.0,text="Bonjour")))
                fail("A voice must be selected explicitly")
            } catch(e:ClientFailure) {assertEquals("mobile.dub.choose_voice",e.key)}
            assertEquals(0,server.requestCount)
            for(voice in listOf("", "cloned-profile")) {
                server.enqueue(MockResponse().setBody("""{"task_id":"render"}"""))
                api.startDub("job","fr","French",voice,listOf(Segment(start=0.0,end=1.0,text="Bonjour")))
                val request=server.takeRequest()
                assertEquals("/dub/generate/job",request.path)
                val segment=json.parseToJsonElement(request.body.readUtf8()).jsonObject.getValue("segments").jsonArray.single().jsonObject
                assertEquals(voice,segment.getValue("profile_id").jsonPrimitive.content)
                assertFalse(segment.containsKey("speaker_id"))
            }
        } finally {server.shutdown()}
    }
}
