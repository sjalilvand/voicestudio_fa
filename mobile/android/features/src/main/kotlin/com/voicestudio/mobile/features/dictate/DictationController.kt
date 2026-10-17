package com.voicestudio.mobile.features.dictate

import android.media.*
import com.voicestudio.mobile.features.guidance
import com.voicestudio.mobile.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.*
import kotlinx.serialization.decodeFromString
import okhttp3.*
import okio.ByteString.Companion.toByteString

class DictationController(private val api:VoiceStudioApi,private val scope:CoroutineScope,private val failure:(Throwable)->Unit) : AutoCloseable {
    private val mutableText=MutableStateFlow("")
    val text=mutableText.asStateFlow()
    private val mutableActive=MutableStateFlow(false)
    val active=mutableActive.asStateFlow()
    private var capture:Job?=null
    private var recorder:AudioRecord?=null
    private var socket:WebSocket?=null
    @Volatile private var recording=false
    private var committed=""
    @Suppress("MissingPermission")
    fun start() {
        if(mutableActive.value) return
        mutableActive.value=true;committed="";mutableText.value="";recording=true
        capture=scope.launch {
            try {
                val readiness=api.readiness()
                if(!readiness.ready) {
                    val (key,params)=readiness.guidance()
                    throw ClientFailure(key,params.mapValues {it.value.toString()})
                }
                val opened=CompletableDeferred<Unit>()
                val ended=CompletableDeferred<Unit>()
                socket=api.client.newWebSocket(api.dictationRequest(),object:WebSocketListener() {
                    override fun onOpen(ws:WebSocket,response:Response) {opened.complete(Unit)}
                    override fun onMessage(ws:WebSocket,message:String) {
                        try {
                            val event=api.json.decodeFromString<DictationEvent>(message)
                            when(event.type) {
                                "partial" -> mutableText.value=listOf(committed,event.text).filter {it.isNotBlank()}.joinToString(" ")
                                "final" -> {
                                    if(event.finalKind=="utterance") committed=listOf(committed,event.text).filter {it.isNotBlank()}.joinToString(" ")
                                    else committed=event.text
                                    mutableText.value=committed
                                }
                                "error" -> {
                                    val e=event.message?.takeIf {it.isNotBlank()}?.let {ClientFailure("mobile.errors.server",mapOf("message" to it))} ?: ClientFailure("mobile.dictate.setup")
                                    failure(e);opened.completeExceptionally(e);ended.complete(Unit);recording=false
                                }
                            }
                        } catch(e:Exception) {failure(e);recording=false;ended.complete(Unit)}
                    }
                    override fun onFailure(ws:WebSocket,t:Throwable,response:Response?) {
                        val e=t as? ClientFailure ?: ClientFailure(if(response?.code in listOf(401,403)) "mobile.dictate.authorization" else "mobile.dictate.setup")
                        opened.completeExceptionally(e);ended.complete(Unit);recording=false
                        if(mutableActive.value) failure(e)
                    }
                    override fun onClosing(ws:WebSocket,code:Int,reason:String) {ws.close(code,null);ended.complete(Unit);recording=false}
                    override fun onClosed(ws:WebSocket,code:Int,reason:String) {ended.complete(Unit);recording=false}
                })
                withTimeout(20000) {opened.await()}
                if(!recording) return@launch
                withContext(Dispatchers.IO) {
                    val size=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT).coerceAtLeast(6400)
                    val device=AudioRecord.Builder().setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                        .setAudioFormat(AudioFormat.Builder().setSampleRate(16000).setChannelMask(AudioFormat.CHANNEL_IN_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build())
                        .setBufferSizeInBytes(size).build()
                    recorder=device
                    try {
                        check(device.state==AudioRecord.STATE_INITIALIZED)
                        device.startRecording();val buffer=ByteArray(3200)
                        while(recording&&isActive) {
                            val n=device.read(buffer,0,buffer.size,AudioRecord.READ_BLOCKING)
                            if(n<0) throw ClientFailure("mobile.android.recording_failed")
                            if(n>0&&socket?.send(buffer.toByteString(0,n))!=true) throw ClientFailure("mobile.dictate.setup")
                            if((socket?.queueSize() ?: 0)>1024*1024) throw ClientFailure("mobile.errors.timeout")
                        }
                    } finally {runCatching {device.stop()};device.release();recorder=null}
                }
                socket?.send("{\"type\":\"input_audio.end\"}")
                withTimeout(60000) {ended.await()}
            } catch(e:TimeoutCancellationException) {failure(ClientFailure("mobile.errors.timeout"))} catch(e:CancellationException) {throw e} catch(e:Exception) {failure(e)}
            finally {recording=false;socket?.close(1000,null);socket=null;mutableActive.value=false}
        }
    }
    fun finish() {recording=false}
    override fun close() {recording=false;capture?.cancel();socket?.cancel();socket=null;mutableActive.value=false}
}
