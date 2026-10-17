package com.voicestudio.mobile

import android.app.Application
import android.os.Looper
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.viewModelScope
import androidx.test.core.app.ApplicationProvider
import com.voicestudio.mobile.data.*
import com.voicestudio.mobile.features.StudioViewModel
import com.voicestudio.mobile.local.ModelCatalog
import kotlinx.coroutines.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk=[34])
class PhoneNavigationTest {
    @get:Rule val compose=createComposeRule()
    @Test fun allTabsAndModelManagementWorkWithoutPairing() = runBlocking {
        val app=ApplicationProvider.getApplicationContext<Application>()
        val vault=object: CredentialVault {
            override fun read(host: String): Secret? = null
            override fun write(host: String,secret: Secret?) = Unit
        }
        val store=SessionStore(app,vault)
        store.update {Preferences(consent=false)}
        val vm=StudioViewModel(app,store)
        try {
            compose.setContent {StudioApp(vm)}
            withTimeout(15000) {while(vm.state.value.loading||vm.phone.state.value.loading) {shadowOf(Looper.getMainLooper()).idle();delay(10)}}
            compose.waitForIdle()
            assertFalse(vm.state.value.connected);assertNull(vm.api)
            fun tab(label: String) = compose.onAllNodesWithText(label).filter(hasClickAction()).onFirst()
            for(label in listOf("Speak","Voices","Dub","Dictate","Settings")) tab(label).assertExists()
            compose.onNodeWithText("Run on").assertExists()
            compose.onNodeWithText("This phone").assertExists()
            tab("Dictate").performClick();compose.onNodeWithText("Tap to start").assertExists()
            tab("Settings").performClick();compose.onNodeWithText("Connect").assertExists()
            compose.onNodeWithText("Appearance").assertExists()
            compose.onNodeWithText("Models").performClick()
            compose.onNodeWithText("Allow model downloads using mobile data").assertExists()
            assertFalse(vm.phone.downloads.progress.value.values.any {it.running})
        } finally {vm.viewModelScope.cancel()}
    }
    @Test fun shippedCatalogueHasEveryRuntimeAndExactLegalDisclosures() {
        val app=ApplicationProvider.getApplicationContext<Application>()
        val catalogue=app.assets.open("models.json").bufferedReader().use {ModelCatalog.decode(it.readText())}
        assertEquals(setOf("sherpa-onnx","omnivoice.cpp","llama.cpp"),catalogue.models.map {it.runtime}.toSet())
        assertEquals(setOf("tts","asr","asr-stream","clone","translate"),catalogue.models.map {it.capability}.toSet())
        for(model in catalogue.models) {
            assertTrue(model.licence.terms.isNotEmpty())
            if(model.licence.category!="commercial-ok") assertTrue(model.gated)
        }
    }
}
