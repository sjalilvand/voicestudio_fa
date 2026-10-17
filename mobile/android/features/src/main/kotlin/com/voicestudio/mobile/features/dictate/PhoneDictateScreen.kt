package com.voicestudio.mobile.features.dictate

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.*
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.voicestudio.mobile.designsystem.*
import com.voicestudio.mobile.features.*
import com.voicestudio.mobile.features.models.ModelCard
import com.voicestudio.mobile.local.*
import com.voicestudio.mobile.network.ClientFailure
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.*
import java.nio.ByteBuffer
import java.nio.ByteOrder

internal class PhoneDictation(private val engine: LocalEngine, private val scope: CoroutineScope, private val failure: (Throwable)->Unit,
    private val microphone: DictationAudioSource = MicrophoneSource()) : AutoCloseable {
    private val mutableText=MutableStateFlow("")
    val text=mutableText.asStateFlow()
    private val mutableActive=MutableStateFlow(false)
    val active=mutableActive.asStateFlow()
    @Volatile private var recording=false
    private var capture: Job?=null
    fun start(model: PhoneModel) {
        if(mutableActive.value) return
        mutableActive.value=true;mutableText.value="";recording=true
        capture=scope.launch {
            try {
                val samples=channelFlow {
                    microphone.record({recording}) {buffer,n ->
                        val pcm=ByteBuffer.wrap(buffer,0,n).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                        val floats=FloatArray(n/2) {pcm.get().toFloat()/32768f}
                        if(!trySend(LocalAudio(floats,16000)).isSuccess) throw ClientFailure("mobile.local.capture_slow")
                    }
                }.buffer(64,BufferOverflow.SUSPEND)
                engine.streamTranscribe(model,samples).collect {mutableText.value=it.text}
            } catch(e:CancellationException) {throw e} catch(e:Exception) {failure(e)}
            finally {recording=false;mutableActive.value=false}
        }
    }
    fun finish() {recording=false}
    override fun close() {recording=false;capture?.cancel()}
}

@Composable internal fun PhoneDictateScreen(vm: StudioViewModel, model: PhoneModel?, ready: Boolean) {
    val context=LocalContext.current
    val scope=rememberCoroutineScope()
    val controller=remember(model?.id) {PhoneDictation(vm.phone.engine,scope,vm::fail)}
    val text by controller.text.collectAsState()
    val active by controller.active.collectAsState()
    val lifecycle=LocalLifecycleOwner.current
    DisposableEffect(lifecycle,controller) {
        val observer=LifecycleEventObserver {_,event -> if(event==Lifecycle.Event.ON_STOP) controller.close()}
        lifecycle.lifecycle.addObserver(observer)
        onDispose {lifecycle.lifecycle.removeObserver(observer);controller.close()}
    }
    var holding by remember {mutableStateOf(false)}
    val start=permissionAction(Manifest.permission.RECORD_AUDIO,"mobile.permissions.microphone",vm::fail) {if(ready&&model!=null) controller.start(model)}
    val holdStart=permissionAction(Manifest.permission.RECORD_AUDIO,"mobile.permissions.microphone",vm::fail) {if(holding&&ready&&model!=null) controller.start(model)}
    Screen {
        ScreenTitle("mobile.tabs.dictate")
        if(!ready) model?.let {ModelCard(vm,it)}
        Action(if(active) "common.stop" else "mobile.dictate.tap_to_start",ready||active) {if(active) controller.finish() else start()}
        val label=tr("mobile.dictate.hold_to_talk")
        Surface(modifier=Modifier.fillMaxWidth().heightIn(min=VSTheme.touchTarget).semantics {
            role=Role.Button;contentDescription=label;onClick {if(active) controller.finish() else if(ready) start();true}
        }.pointerInput(ready,controller) {detectTapGestures(onPress={if(ready) {holding=true;holdStart();tryAwaitRelease();holding=false;controller.finish()}})},color=role("surface"),shape=MaterialTheme.shapes.small) {
            Text(label,Modifier.padding(VSTheme.inset))
        }
        if(active) Text(tr("mobile.dictate.listening"))
        Text(text,modifier=Modifier.semantics {liveRegion=LiveRegionMode.Polite})
        Secondary("mobile.dictate.copy",text.isNotBlank()) {context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText(null,text))}
        Secondary("mobile.speak.share",text.isNotBlank()) {shareText(context,text)}
    }
}
