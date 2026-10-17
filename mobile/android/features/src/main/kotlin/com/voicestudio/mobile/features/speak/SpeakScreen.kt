package com.voicestudio.mobile.features.speak

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.*
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.voicestudio.mobile.designsystem.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.platform.LocalContext
import com.voicestudio.mobile.features.*
import java.io.File
import kotlinx.coroutines.*

@Composable private fun ComputerSpeakScreen(vm:StudioViewModel) {
    val state by vm.state.collectAsState()
    val context=LocalContext.current
    val scope=rememberCoroutineScope()
    var text by rememberSaveable {mutableStateOf("")}
    var voice by rememberSaveable {mutableStateOf("")}
    var engine by rememberSaveable {mutableStateOf("")}
    var language by rememberSaveable {mutableStateOf("Auto")}
    val catalog=rememberLanguageCatalog(vm::fail)
    val l=LocalL10n.current
    val profile=state.profiles.firstOrNull {it.id==voice}
    val engines=engineChoices(state.engines,profile) {l.t(it)}
    var savePath by rememberSaveable {mutableStateOf<String?>(null)}
    val save=rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("audio/wav")) {uri ->
        val path=savePath;savePath=null
        if(uri!=null && path!=null) scope.launch {
            try {val file=sharedDownload(context,vm.api!!,path,"wav");withContext(Dispatchers.IO) {context.contentResolver.openOutputStream(uri)!!.use {out -> file.inputStream().use {it.copyTo(out)}}};file.delete()}
            catch(e:Exception) {vm.fail(e)}
        }
    }
    LaunchedEffect(state.profiles) {if(voice.isNotBlank() && profile==null) voice=""}
    LaunchedEffect(voice,profile?.language,catalog) {language=catalog?.preferred(profile) ?: "Auto"}
    LaunchedEffect(engines,state.engines.active) {
        if(engines.none {it.id==engine && it.enabled}) engine=initialEngine(state.engines,engines)
    }
    Screen {
        ScreenTitle("mobile.tabs.speak")
        Field("mobile.speak.placeholder",text,{text=it},multiline=true)
        if(catalog==null) InlineLoading()
        Group {
            Picker("mobile.speak.voice",voice,listOf("" to tr("mobile.speak.voice_default"))+state.profiles.map {it.id to it.name},{voice=it})
            HorizontalDivider()
            ChoicePicker("mobile.speak.engine",engine,engines,{engine=it})
            HorizontalDivider()
            Picker("mobile.speak.language",language,catalog?.names.orEmpty().map {it to it},{language=it})
        }
        Action(if(state.busy) "mobile.speak.generating" else "mobile.speak.generate",text.isNotBlank()&&engines.any {it.id==engine&&it.enabled}&&!state.busy) {
            vm.generate(text,voice,engine,language)
        }
        val audio=state.audio;val api=vm.api
        if(audio!=null && api!=null) {
            HostPlayer(api,audio,vm::fail)
            Secondary("mobile.speak.share",!state.busy) {vm.run {shareFile(context,sharedDownload(context,api,audio,"wav"),"audio/wav")}}
            Secondary("common.save",!state.busy) {savePath=audio;save.launch("${java.util.UUID.randomUUID()}.wav")}
        }
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) {Heading("mobile.speak.recent")}
            IconAction("common.refresh",Icons.Default.Refresh,!state.busy,onClick=vm::refresh)
        }
        if(state.catalogLoading) InlineLoading()
        else if(state.history.isEmpty()) Text(tr("mobile.speak.empty_recent"),color=role("textMuted"))
        if(state.history.isNotEmpty()) Group {
            state.history.forEach {item ->
                Row(Modifier.fillMaxWidth().padding(VSTheme.inset),verticalAlignment=Alignment.CenterVertically) {
                    Text(item.text,Modifier.weight(1f),style=MaterialTheme.typography.bodyMedium)
                    IconAction("player.play",Icons.Default.PlayArrow) {vm.play(vm.api!!.audioPath(item.audioPath))}
                    IconAction(if(item.isStarred) "mobile.speak.unstar" else "mobile.speak.star",Icons.Default.Star,!state.busy) {vm.star(item)}
                    IconAction("common.delete",Icons.Default.Delete,!state.busy) {vm.deleteHistory(item)}
                }
                HorizontalDivider()
            }
        }
    }
}

@Composable fun SpeakScreen(vm: StudioViewModel) {
    com.voicestudio.mobile.features.models.TaskLocation(vm,"speak",setOf("tts")) {location,model ->
        if(location==com.voicestudio.mobile.local.RunLocation.COMPUTER) ComputerSpeakScreen(vm)
        else {
            val phone by vm.phone.state.collectAsState()
            val context=LocalContext.current
            val scope=rememberCoroutineScope()
            var text by rememberSaveable {mutableStateOf("")}
            var speaker by rememberSaveable(model?.id) {mutableStateOf("0")}
            val save=rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("audio/wav")) {uri ->
                val source=phone.audio
                if(uri!=null&&source!=null) scope.launch {
                    try {withContext(Dispatchers.IO) {context.contentResolver.openOutputStream(uri)!!.use {out -> source.inputStream().use {it.copyTo(out)}}}}
                    catch(e:Exception) {vm.fail(e)}
                }
            }
            DisposableEffect(Unit) {onDispose {vm.phone.cancelInference()}}
            Screen {
                ScreenTitle("mobile.tabs.speak")
                Field("mobile.speak.placeholder",text,{text=it},multiline=true)
                val speakers=model?.option("num_speakers",model.option("speaker_count","1"))?.toIntOrNull()?.coerceIn(1,128) ?: 1
                Picker("mobile.speak.voice",speaker,(0 until speakers).map {it.toString() to tr("mobile.local.preset_voice",mapOf("number" to it+1))}) {speaker=it}
                model?.let {Text(tr("mobile.local.languages",mapOf("languages" to it.languages.joinToString(", "))))}
                if(location==com.voicestudio.mobile.local.RunLocation.DOWNLOAD||model?.let {phone.accepted(it)}==false) model?.let {com.voicestudio.mobile.features.models.ModelCard(vm,it)}
                else Action("mobile.speak.generate",text.isNotBlank()&&model!=null&&phone.progress==null) {vm.phone.speak(model!!,text,speaker.toInt())}
                phone.progress?.let {p ->
                    LinearProgressIndicator(progress={p},modifier=Modifier.fillMaxWidth())
                    Secondary("common.cancel") {vm.phone.cancelInference()}
                }
                phone.audio?.let {file ->
                    LocalAudioPlayer(file,vm::fail)
                    Secondary("mobile.speak.share") {shareFile(context,file,"audio/wav")}
                    Secondary("common.save") {save.launch(file.name)}
                }
            }
        }
    }
}
