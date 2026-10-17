package com.voicestudio.mobile.features.models

import android.text.format.Formatter
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.dp
import com.voicestudio.mobile.designsystem.*
import com.voicestudio.mobile.features.*
import com.voicestudio.mobile.local.*

@Composable fun ModelsScreen(vm: StudioViewModel) {
    val state by vm.phone.state.collectAsState()
    val preferences by vm.preferences.collectAsState()
    Screen {
        ScreenTitle("mobile.local.models")
        Text(tr("mobile.local.storage_used",mapOf("size" to Formatter.formatFileSize(LocalContext.current,state.used))))
        Toggle("mobile.simple.mobile_data",preferences.allowMobileModels) {allowed -> vm.preference {it.copy(allowMobileModels=allowed)}}
        if(state.loading) InlineLoading()
        state.models.forEach {model -> ModelCard(vm,model)}
    }
}
@OptIn(ExperimentalMaterial3Api::class)
@Composable fun ModelCard(vm: StudioViewModel, model: PhoneModel) {
    val state by vm.phone.state.collectAsState()
    val progress by vm.phone.downloads.progress.collectAsState()
    val preferences by vm.preferences.collectAsState()
    val context=LocalContext.current
    var terms by remember(model.id,model.licence.termsFingerprint) {mutableStateOf(false)}
    var checked by remember(terms) {mutableStateOf(false)}
    val installed=model.id in state.installed
    val fits=model.fits(vm.phone.ramBytes)
    val downloading=progress[model.id]?.running==true
    Group {
        Column(Modifier.fillMaxWidth().padding(VSTheme.inset),verticalArrangement=Arrangement.spacedBy(VSTheme.gap)) {
            Text(model.id,style=MaterialTheme.typography.titleMedium)
            Text(Formatter.formatFileSize(context,model.totalBytes))
            Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
                Text(tr("mobile.simple.${model.capability}"),Modifier.weight(1f),style=MaterialTheme.typography.labelSmall)
                TextButton(onClick={terms=true}) {Text(model.licence.id)}
            }
            if(!fits) Text(tr("mobile.simple.ram",mapOf("ram" to model.minRamGb)),color=role("textMuted"))
            progress[model.id]?.let {p ->
                if(p.running) {
                    LinearProgressIndicator(progress={if(p.total>0) (p.received.toFloat()/p.total).coerceIn(0f,1f) else 0f},modifier=Modifier.fillMaxWidth())
                    Text(tr("mobile.local.transfer",mapOf("received" to Formatter.formatFileSize(context,p.received),"total" to Formatter.formatFileSize(context,p.total))))
                }
                p.error?.let {Text(tr(shortErrorKey(it)),color=role("error"),maxLines=1)}
            }
            if(downloading) Secondary("common.cancel") {vm.phone.cancelDownload(model)}
            else if(!installed) Secondary("mobile.local.download",fits) {
                try {if(!vm.phone.licence.accepted(model)) terms=true else vm.phone.download(model,preferences.allowMobileModels)} catch(e:Exception) {vm.fail(e)}
            } else Secondary("common.delete") {vm.phone.delete(model)}
        }
    }
    if(terms) ModalBottomSheet(containerColor=role("surfaceOverlay"),onDismissRequest={terms=false}) {
        Column(Modifier.fillMaxWidth().heightIn(max=(LocalConfiguration.current.screenHeightDp*.65f).dp).padding(VSTheme.inset).verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(VSTheme.gap)) {
            Text(model.id)
            Text(model.languages.joinToString(", "))
            Text(tr("mobile.local.storage_used",mapOf("size" to Formatter.formatFileSize(context,state.storage[model.id] ?: 0))))
            Text(tr("mobile.local.licence_label",mapOf("licence" to model.licence.id,"category" to model.licence.category)))
            Text(model.licence.credit);Text(model.licence.rightsHolder)
            androidx.compose.foundation.text.selection.SelectionContainer {
                val disclosure=remember(model.licence.terms) {kotlinx.serialization.json.Json {prettyPrint=true}.encodeToString(kotlinx.serialization.json.JsonObject.serializer(),model.licence.terms)}
                Text(disclosure)
            }
            Text(tr("mobile.local.terms_fingerprint",mapOf("fingerprint" to model.licence.termsFingerprint)))
            state.receipts[model.id].orEmpty().asReversed().forEach {receipt ->
                Text(tr("mobile.local.receipt",mapOf("action" to tr(if(receipt.accepted) "mobile.local.accepted" else "mobile.local.not_accepted"),"time" to java.text.DateFormat.getDateTimeInstance().format(java.util.Date(receipt.time)),"version" to receipt.appVersion,"fingerprint" to receipt.fingerprint)))
            }
            Text(tr("mobile.local.licensor_notice"))
            if(!installed&&!downloading&&(state.storage[model.id] ?: 0)>0) Secondary("common.delete") {vm.phone.delete(model);terms=false}
            ConsentCheck("mobile.local.licence_confirm",checked) {checked=it}
            Secondary("mobile.local.withdraw") {vm.phone.accept(model,false,model.licence.termsFingerprint);terms=false}
        }
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceEvenly) {
            TextButton(onClick={terms=false}) {Text(tr("mobile.simple.decline"))}
            TextButton(enabled=checked,onClick={vm.phone.accept(model,true,model.licence.termsFingerprint);terms=false}) {Text(tr("mobile.simple.accept"))}
        }
    }
}

@Composable fun TaskLocation(vm: StudioViewModel, task: String, capabilities: Set<String>, dependencies: Set<String> = emptySet(), content: @Composable (RunLocation,PhoneModel?)->Unit) {
    val host by vm.state.collectAsState()
    val phone by vm.phone.state.collectAsState()
    val preferences by vm.preferences.collectAsState()
    var models by remember {mutableStateOf(false)}
    val choices=phone.models.filter {it.capability in capabilities}
    val selected=choices.firstOrNull {it.id==preferences.phoneModels[task]} ?: choices.firstOrNull {it.id in phone.installed&&it.fits(vm.phone.ramBytes)} ?: choices.firstOrNull()
    val ready=selected?.let {it.id in phone.installed&&it.fits(vm.phone.ramBytes)}==true&&dependencies.all {cap -> phone.models.any {it.capability==cap&&it.id in phone.installed&&it.fits(vm.phone.ramBytes)}}
    val location=routeTask(preferences.runLocations[task],ready,host.connected)
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal=VSTheme.inset),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(VSTheme.gap)) {
            if(host.connected) {
                if(LocalDensity.current.fontScale<=1.5f) Text(tr("mobile.local.run_on"),style=MaterialTheme.typography.labelSmall)
                SingleChoiceSegmentedButtonRow(Modifier.weight(1f)) {
                    listOf("phone" to "mobile.local.this_phone","computer" to "mobile.simple.computer").forEachIndexed {index,(id,key) ->
                        SegmentedButton(selected=(location==RunLocation.COMPUTER)==(id=="computer"),onClick={vm.phone.cancelInference();vm.preference {it.copy(runLocations=it.runLocations+(task to id))}},shape=SegmentedButtonDefaults.itemShape(index,2)) {Text(tr(key),maxLines=1,overflow=TextOverflow.Ellipsis)}
                    }
                }
            } else Spacer(Modifier.weight(1f))
            IconAction("mobile.local.models",Icons.Default.Settings) {models=!models}
        }
        if(location!=RunLocation.COMPUTER&&task !in setOf("speak","dub")) TaskModelPicker(vm,task,capabilities,selected,compact=true)
        Box(Modifier.weight(1f)) {if(models) ModelsScreen(vm) else content(location,selected)}
    }
}

@Composable fun TaskModelPicker(vm: StudioViewModel, task: String, capabilities: Set<String>, selected: PhoneModel?, compact: Boolean = false) {
    val phone by vm.phone.state.collectAsState()
    ChoicePicker("mobile.local.model",selected?.id.orEmpty(),phone.models.filter {it.capability in capabilities}.map {
        Choice(it.id,it.id,enabled=it.fits(vm.phone.ramBytes),supporting=if(it.fits(vm.phone.ramBytes)) null else tr("mobile.local.ram_required",mapOf("ram" to it.minRamGb)))
    },compact=compact) {id -> vm.phone.cancelInference();vm.preference {it.copy(phoneModels=it.phoneModels+(task to id))}}
}
