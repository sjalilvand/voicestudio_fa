package com.voicestudio.mobile.features.dub

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.*
import androidx.compose.foundation.layout.*
import androidx.compose.ui.semantics.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.platform.LocalContext
import androidx.work.WorkManager
import androidx.work.WorkInfo
import com.voicestudio.mobile.features.*
import com.voicestudio.mobile.data.DubWorker
import com.voicestudio.mobile.network.*
import kotlinx.coroutines.*
import java.io.File
import kotlinx.serialization.json.*

@Composable fun DubScreen(vm:StudioViewModel) {
    val context=LocalContext.current
    val state by vm.state.collectAsState()
    val prefs by vm.preferences.collectAsState()
    val work=remember {WorkManager.getInstance(context)}
    val workFlow=remember(prefs.activeUrl) {work.getWorkInfosByTagFlow(prefs.activeUrl ?: DubWorker.TAG)}
    val works by workFlow.collectAsState(emptyList())
    val scope=rememberCoroutineScope()
    var link by rememberSaveable {mutableStateOf("")}
    var filePath by rememberSaveable {mutableStateOf<String?>(null)}
    var inputType by rememberSaveable {mutableStateOf("video")}
    var targets by rememberSaveable {mutableStateOf(listOf<String>())}
    var voice by rememberSaveable {mutableStateOf("")}
    var copying by remember {mutableStateOf(false)}
    val catalog=remember {LanguageCatalog.load(context)}
    val languages=remember(catalog) {catalog.dubChoices()}
    LaunchedEffect(state.profiles) {if(state.profiles.none {it.id==voice}) voice=state.profiles.firstOrNull()?.id.orEmpty()}
    val picker=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) {uri ->
        if(uri!=null) scope.launch {
            copying=true
            try {filePath?.let {File(it).delete()};inputType=if(context.contentResolver.getType(uri)?.startsWith("audio/")==true) "audio" else "video";filePath=copyMedia(context,uri,if(inputType=="audio") "m4a" else "mp4").absolutePath}
            catch(e:Exception) {vm.fail(e)} finally {copying=false}
        }
    }
    Screen {
        ScreenTitle("mobile.tabs.dub")
        Text(tr("mobile.dub.runs_on_host"))
        Secondary("mobile.dub.pick_media",!copying) {picker.launch(arrayOf("video/*","audio/*"))}
        if(filePath!=null) {
            Text(File(filePath!!).name)
            Secondary("common.delete") {File(filePath!!).delete();filePath=null}
        }
        Field("mobile.dub.paste_url",link,{link=it})
        MultiPicker("mobile.dub.target_languages",targets,languages) {targets=it}
        Group {Picker("mobile.speak.voice",voice,state.profiles.map {it.id to it.name},{voice=it})}
        Action("mobile.dub.start",!copying&&voice.isNotBlank()&&targets.isNotEmpty()&&(filePath!=null||link.isNotBlank())) {
            try {
                DubWorker.enqueue(context,prefs.activeUrl!!,filePath?.let(::File),link.takeIf {filePath==null},inputType,languages.filter {it.first in targets},voice)
                filePath=null;link=""
            } catch(e:Exception) {vm.fail(e)}
        }
        works.forEach {info ->
            val stage=info.displayStage()
            val errorParams=remember(info.outputData) {runCatching {
                Json.parseToJsonElement(info.outputData.getString("error_params") ?: "{}").jsonObject.mapValues {it.value.jsonPrimitive.content}
            }.getOrDefault(emptyMap())}
            Text(LocalL10n.current.t(stage,errorParams))
            if(!info.state.isFinished) {
                val progress=info.progress.getInt("percent",0)
                if(progress>0) LinearProgressIndicator(progress={progress/100f}) else LinearProgressIndicator()
                Secondary("mobile.dub.abort") {
                    val job=info.progress.getString("job")
                    vm.run {
                        // Stop host work before cancelling the durable monitor.
                        if(job!=null) vm.api?.abort(job)
                        work.cancelWorkById(info.id)
                    }
                }
            }
            val job=info.outputData.getString("job") ?: info.progress.getString("job")
            if(info.state==WorkInfo.State.SUCCEEDED&&job!=null) Secondary("mobile.dub.download",!state.busy) {
                vm.run {shareFile(context,sharedDownload(context,vm.api!!,"/dub/download/${VoiceStudioApi.segment(job)}",if(inputType=="audio") "m4a" else "mkv"),"application/octet-stream")}
            }
            HorizontalDivider()
        }
        Heading("mobile.dub.history")
        Secondary("common.refresh",!state.busy,vm::refresh)
        if(state.dubHistory.isEmpty()) Text(tr("mobile.dub.empty_history"))
        state.dubHistory.forEach {item ->
            Text(item.filename.ifBlank {item.id})
            Secondary("mobile.dub.download",!state.busy) {vm.run {shareFile(context,sharedDownload(context,vm.api!!,"/dub/download/${VoiceStudioApi.segment(item.jobId.ifBlank {item.id})}","mkv"),"application/octet-stream")}}
        }
    }
}

/** Terminal failures take precedence over the last persisted progress update. */
fun WorkInfo.displayStage(): String = when(state) {
    WorkInfo.State.FAILED -> outputData.getString("error") ?: "mobile.android.job_failed"
    WorkInfo.State.SUCCEEDED -> "mobile.android.stage_done"
    WorkInfo.State.CANCELLED -> "mobile.android.stage_cancelled"
    WorkInfo.State.ENQUEUED -> if(runAttemptCount>0) "mobile.errors.offline" else progress.getString("stage") ?: "mobile.android.stage_prepare"
    else -> progress.getString("stage") ?: outputData.getString("stage") ?: "mobile.android.stage_prepare"
}
