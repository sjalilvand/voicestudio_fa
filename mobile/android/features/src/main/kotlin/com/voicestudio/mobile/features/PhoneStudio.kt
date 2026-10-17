package com.voicestudio.mobile.features

import android.app.ActivityManager
import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.voicestudio.mobile.local.*
import com.voicestudio.mobile.network.ClientFailure
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import java.io.File

data class PhoneState(val models: List<PhoneModel> = emptyList(), val installed: Set<String> = emptySet(), val used: Long = 0,
    val storage: Map<String,Long> = emptyMap(), val receipts: Map<String,List<LicenceReceipt>> = emptyMap(), val loading: Boolean = true, val progress: Float? = null, val audio: File? = null) {
    fun accepted(model: PhoneModel): Boolean = !model.gated || receipts[model.id]?.lastOrNull()?.let {it.accepted&&it.fingerprint==model.licence.termsFingerprint}==true
}
class PhoneStudio(context: Context, private val scope: CoroutineScope, private val failure: (Throwable)->Unit) {
    private val application=context.applicationContext
    val ramBytes=ActivityManager.MemoryInfo().also {application.getSystemService(ActivityManager::class.java).getMemoryInfo(it)}.totalMem
    private val root=File(application.noBackupFilesDir,"models")
    @Suppress("DEPRECATION")
    val licence=LicenceGate(File(application.noBackupFilesDir,"model-licences.json"),application.packageManager.getPackageInfo(application.packageName,0).versionName.orEmpty())
    val downloads=ModelDownloads(root,licence,ramBytes) {
        val connectivity=application.getSystemService(ConnectivityManager::class.java)
        connectivity.activeNetwork?.let {connectivity.getNetworkCapabilities(it)}?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)==true
    }
    val engine: LocalEngine=PhoneLocalEngine(downloads)
    private val mutable=MutableStateFlow(PhoneState())
    val state=mutable.asStateFlow()
    private val jobs=mutableMapOf<String,Job>()
    private var inference: Job?=null
    init {scope.launch {
        try {
            val models=withContext(Dispatchers.IO) {application.assets.open("models.json").bufferedReader().use {ModelCatalog.decode(it.readText()).models}}
            mutable.update {it.copy(models=models,loading=false)};refresh()
        } catch(e:CancellationException) {throw e} catch(e:Exception) {mutable.update {it.copy(loading=false)};failure(ClientFailure("mobile.local.catalogue_failed"))}
    }}
    suspend fun refresh() = withContext(Dispatchers.IO) {
        val installed=mutable.value.models.filter(downloads::installed).map {it.id}.toSet()
        val used=downloads.usedBytes()
        val storage=mutable.value.models.associate {it.id to downloads.usedBytes(it)}
        val receipts=mutable.value.models.associate {it.id to licence.history(it)}
        mutable.update {it.copy(installed=installed,used=used,storage=storage,receipts=receipts)}
    }
    fun download(model: PhoneModel, allowMobile: Boolean) {
        if(jobs[model.id]?.isActive==true) return
        jobs[model.id]=scope.launch {
            try {downloads.download(model,allowMobile)}
            catch(e:CancellationException) {throw e}
            catch(e:Exception) {failure(e)}
            finally {withContext(NonCancellable) {refresh()}}
        }
    }
    fun cancelDownload(model: PhoneModel) {jobs[model.id]?.cancel()}
    fun delete(model: PhoneModel) {scope.launch {
        try {jobs[model.id]?.cancelAndJoin();cancelInference();downloads.delete(model);refresh()}
        catch(e:CancellationException) {throw e} catch(e:Exception) {failure(e)}
    }}
    fun accept(model: PhoneModel, accepted: Boolean, fingerprint: String) {scope.launch {
        try {
            if(!accepted) {jobs[model.id]?.cancelAndJoin();cancelInference()}
            withContext(Dispatchers.IO) {licence.record(model,accepted,fingerprint)};refresh()
        } catch(e:CancellationException) {throw e} catch(e:Exception) {failure(e)}
    }}
    fun speak(model: PhoneModel, text: String, speaker: Int) {
        if(inference?.isActive==true) return
        inference=scope.launch {
            mutable.update {it.copy(progress=0f)}
            try {
                val audio=engine.synthesize(model,text,speaker,progress={value -> mutable.update {it.copy(progress=value)}})
                val file=withContext(Dispatchers.IO) {
                    val output=File(application.cacheDir,"shared/${java.util.UUID.randomUUID()}.wav")
                    markSynthetic(audio,output);output
                }
                mutable.update {it.copy(audio=file)}
            } catch(e:CancellationException) {throw e} catch(e:Exception) {failure(e)}
            finally {mutable.update {it.copy(progress=null)}}
        }
    }
    fun cancelInference() {inference?.cancel()}
}
