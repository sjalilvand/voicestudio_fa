package com.voicestudio.mobile.features.models

import android.text.format.Formatter
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
        Toggle("mobile.local.allow_mobile",preferences.allowMobileModels) {allowed -> vm.preference {it.copy(allowMobileModels=allowed)}}
        if(state.loading) InlineLoading()
        state.models.forEach {model -> ModelCard(vm,model)}
    }
}
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
            Text(tr("mobile.local.storage_used",mapOf("size" to Formatter.formatFileSize(context,state.storage[model.id] ?: 0))))
            Text(tr("mobile.local.languages",mapOf("languages" to model.languages.joinToString(", "))))
            Text(tr("mobile.local.licence_label",mapOf("licence" to model.licence.id,"category" to model.licence.category)))
            if(!fits) Text(tr("mobile.local.ram_required",mapOf("ram" to model.minRamGb)),color=role("textMuted"))
            if(installed) Text(tr("mobile.local.installed"))
            progress[model.id]?.let {p ->
                if(p.running) {
                    LinearProgressIndicator(progress={if(p.total>0) (p.received.toFloat()/p.total).coerceIn(0f,1f) else 0f},modifier=Modifier.fillMaxWidth())
                    Text(tr("mobile.local.transfer",mapOf("received" to Formatter.formatFileSize(context,p.received),"total" to Formatter.formatFileSize(context,p.total))))
                }
                p.error?.let {Text(tr(it),color=role("error"))}
            }
            state.receipts[model.id]?.lastOrNull()?.let {receipt -> Text(tr(if(receipt.accepted&&receipt.fingerprint==model.licence.termsFingerprint) "mobile.local.accepted" else "mobile.local.not_accepted"))}
            if(model.gated) Secondary("mobile.local.review_licence") {terms=true}
            if(downloading) Secondary("common.cancel") {vm.phone.cancelDownload(model)}
            else if(!installed) Secondary("mobile.local.download",fits) {
                try {if(!vm.phone.licence.accepted(model)) terms=true else vm.phone.download(model,preferences.allowMobileModels)} catch(e:Exception) {vm.fail(e)}
            }
            // Delete also removes retained resume fragments after cancellation.
            Secondary("common.delete",!downloading) {vm.phone.delete(model)}
        }
    }
    if(terms) AlertDialog(shape=MaterialTheme.shapes.large,containerColor=role("surfaceOverlay"),onDismissRequest={terms=false},title={Text(tr("mobile.local.review_licence"))},text={
        Column(Modifier.verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(VSTheme.gap)) {
            Text(model.id)
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
            Toggle("mobile.local.licence_confirm",checked) {checked=it}
            Secondary("mobile.local.withdraw") {vm.phone.accept(model,false,model.licence.termsFingerprint);terms=false}
        }
    },confirmButton={TextButton(enabled=checked,onClick={vm.phone.accept(model,true,model.licence.termsFingerprint);terms=false}) {Text(tr("mobile.local.accept_licence"))}},dismissButton={TextButton(onClick={terms=false}) {Text(tr("common.cancel"))}})
}

@Composable fun TaskLocation(vm: StudioViewModel, task: String, capabilities: Set<String>, content: @Composable (RunLocation,PhoneModel?)->Unit) {
    val host by vm.state.collectAsState()
    val phone by vm.phone.state.collectAsState()
    val preferences by vm.preferences.collectAsState()
    var models by remember {mutableStateOf(false)}
    val choices=phone.models.filter {it.capability in capabilities}
    val selected=choices.firstOrNull {it.id==preferences.phoneModels[task]} ?: choices.firstOrNull {it.id in phone.installed&&it.fits(vm.phone.ramBytes)} ?: choices.firstOrNull()
    val location=routeTask(preferences.runLocations[task],selected?.id in phone.installed,host.connected)
    Column(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxWidth().heightIn(max=(LocalConfiguration.current.screenHeightDp*.45f).dp).verticalScroll(rememberScrollState()).padding(VSTheme.inset),verticalArrangement=Arrangement.spacedBy(VSTheme.gap)) {
            ChoicePicker("mobile.local.run_on",if(location==RunLocation.COMPUTER) "computer" else "phone",listOf(
                Choice("phone",tr("mobile.local.this_phone")),Choice("computer",tr("mobile.local.my_computer"),enabled=host.connected,supporting=if(host.connected) null else tr("mobile.local.pair_settings")))) {value ->
                vm.phone.cancelInference();vm.preference {it.copy(runLocations=it.runLocations+(task to value))}
            }
            if(location!=RunLocation.COMPUTER) {
                ChoicePicker("mobile.local.model",selected?.id.orEmpty(),choices.map {Choice(it.id,it.id,enabled=it.fits(vm.phone.ramBytes),supporting=if(it.fits(vm.phone.ramBytes)) null else tr("mobile.local.ram_required",mapOf("ram" to it.minRamGb)))}) {id ->
                    vm.phone.cancelInference();vm.preference {it.copy(phoneModels=it.phoneModels+(task to id))}
                }
                if(location==RunLocation.DOWNLOAD) {
                    if(phone.loading) InlineLoading()
                    selected?.let {Text(tr("mobile.local.inline_download",mapOf("size" to Formatter.formatFileSize(LocalContext.current,it.totalBytes))))}
                }
                Secondary("mobile.local.models") {models=!models}
            }
        }
        Box(Modifier.weight(1f)) {if(models) ModelsScreen(vm) else content(location,selected)}
    }
}
