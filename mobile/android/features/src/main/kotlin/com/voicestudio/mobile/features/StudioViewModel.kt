package com.voicestudio.mobile.features

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.work.WorkManager
import com.voicestudio.mobile.data.*
import com.voicestudio.mobile.network.*
import kotlinx.coroutines.*
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.*
import java.io.File

 data class StudioState(val loading: Boolean = true, val connected: Boolean = false, val busy: Boolean = false,
    val error: ClientFailure? = null, val profiles: List<Profile> = emptyList(), val engines: EngineFamily = EngineFamily(),
    val history: List<HistoryItem> = emptyList(), val dubHistory: List<DubHistory> = emptyList(), val audio: String? = null)

class StudioViewModel @JvmOverloads constructor(application: Application, val store: SessionStore = SessionStore(application)) : AndroidViewModel(application) {
    val preferences = store.preferences.stateIn(viewModelScope, SharingStarted.Eagerly, Preferences())
    private val mutable = MutableStateFlow(StudioState())
    val state: StateFlow<StudioState> = mutable.asStateFlow()
    var api: VoiceStudioApi? = null
        private set
    private var operation: Job? = null
    init {
        viewModelScope.launch {
            val prefs = store.preferences.first()
            prefs.activeUrl?.let { host ->
                api = store.api(host, ::expired)
                mutable.update { it.copy(connected = true) }
            }
            mutable.update { it.copy(loading = false) }
            if(api != null) refresh()
        }
    }
    private fun expired() {
        viewModelScope.launch {
            WorkManager.getInstance(getApplication()).cancelAllWorkByTag(DubWorker.TAG)
            store.disconnect(); api = null
            mutable.value = StudioState(loading = false, error = ClientFailure("mobile.connect.error_session_expired"))
        }
    }
    fun clearError() { mutable.update { it.copy(error = null) } }
    fun fail(error: Throwable) {
        if(error is CancellationException) return
        mutable.update { it.copy(error = error as? ClientFailure ?: ClientFailure("mobile.android.operation_failed")) }
    }
    fun run(block: suspend () -> Unit) {
        if(mutable.value.busy) return
        operation = viewModelScope.launch {
            mutable.update { it.copy(busy = true, error = null) }
            try { block() } catch(e: CancellationException) { throw e } catch(e: Exception) { fail(e) }
            finally { mutable.update { it.copy(busy = false) } }
        }
    }
    fun cancel() { operation?.cancel() }
    fun consent(value: Boolean) { viewModelScope.launch { store.update { it.copy(consent = value) } } }
    fun preference(transform: (Preferences) -> Preferences) { viewModelScope.launch { store.update(transform) } }
    fun connect(raw: String, pin: String, key: String) = run {
        val address = PairingAddress.parse(raw, pin)
        val candidate = VoiceStudioApi(address)
        candidate.health()
        if(key.isNotBlank()) candidate.exchange(key)
        // Health is public: a protected consumption endpoint must also succeed.
        val profiles = candidate.profiles()
        store.pair(address, Secret(candidate.sessionToken, address.pin))
        api = store.api(address.baseUrl.toString(), ::expired)
        mutable.update { it.copy(connected = true, profiles = profiles) }
        reload()
    }
    fun reconnect(host: SavedHost) = run {
        val candidate = store.api(host.url)
        candidate.health(); val profiles = candidate.profiles()
        val secret = withContext(Dispatchers.IO) {store.vault.read(host.url)} ?: Secret()
        store.pair(candidate.address, secret)
        api = store.api(host.url, ::expired)
        mutable.update { it.copy(connected = true, profiles = profiles) }; reload()
    }
    fun disconnect() = run {
        // Always clear this phone even when the host is offline. The server's
        // bounded session expires if the best-effort revoke could not reach it.
        var revokeError: ClientFailure?=null
        try {api?.revoke()} catch(e:ClientFailure) {if(e.status!=401) revokeError=ClientFailure("mobile.android.disconnected_offline")}
        WorkManager.getInstance(getApplication()).cancelAllWorkByTag(DubWorker.TAG)
        store.disconnect(); api = null; mutable.value = StudioState(loading = false,error=revokeError)
    }
    private suspend fun reload() {
        val current = api ?: return
        val profiles = current.profiles()
        val engines = current.engines().tts
        val history = current.history()
        val dubs = current.dubHistory()
        if(api === current) mutable.update { it.copy(profiles = profiles, engines = engines, history = history, dubHistory = dubs) }
    }
    fun refresh() = run { reload() }
    fun generate(text: String, voice: String, engine: String, language: String) = run {
        val current = api ?: return@run
        val result = current.generate(text, voice, engine, language)
        mutable.update { it.copy(audio = current.audioPath(result.audioPath)) }
        mutable.update { it.copy(history = current.history()) }
    }
    fun play(path: String) { mutable.update { it.copy(audio = path) } }
    fun star(item: HistoryItem) = run { api?.star(item.id, !item.isStarred); reload() }
    fun deleteHistory(item: HistoryItem) = run { api?.deleteHistory(item.id); reload() }
    fun clone(name: String, file: File) = run { api?.clone(name, file); file.delete(); reload() }
    fun rename(id: String, name: String) = run { api?.rename(id, name); reload() }
    fun deleteProfile(id: String) = run { api?.deleteProfile(id); reload() }
    fun forget(url: String) = run { store.forget(url) }
}
