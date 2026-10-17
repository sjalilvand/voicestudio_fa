package com.voicestudio.mobile.features

import android.content.Context
import com.voicestudio.mobile.network.*
import kotlinx.serialization.json.*
import java.util.Locale
import com.voicestudio.mobile.l10n.L10n
import com.voicestudio.mobile.designsystem.VSTokens

/** Desktop's canonical display names, copied by bundleCatalogs rather than maintained here. */
class LanguageCatalog(val names: List<String>) {
    fun canonical(value: String?): String? {
        if(value.isNullOrBlank()) return null
        names.firstOrNull { it.equals(value, true) }?.let { return it }
        val display = Locale.forLanguageTag(value).getDisplayLanguage(Locale.ENGLISH)
        return names.firstOrNull { it.equals(display, true) || it.equals("Standard $display",true) }
    }
    fun preferred(profile: Profile?): String = canonical(profile?.language) ?: "Auto"
    fun dubChoices(): List<Pair<String, String>> = names.filterNot { it == "Auto" }.map { name ->
        // The host accepts language names as well as ISO codes. Preserve names for
        // desktop's long-tail languages that Android's locale database cannot map.
        (languageCode(name) ?: name) to name
    }.distinctBy { it.first }
    companion object {
        fun load(context: Context) = LanguageCatalog(context.assets.open("languages.json").bufferedReader().use {
            Json.parseToJsonElement(it.readText()).jsonArray.map { value -> value.jsonPrimitive.content }
        })
    }
}

data class Choice(val id: String, val title: String, val enabled: Boolean = true, val supporting: String? = null)
fun engineChoices(family: EngineFamily, profile: Profile?, text: (String) -> String): List<Choice> = family.backends.map { engine ->
    val incompatible = profile?.hasReferenceAudio == true && engine.supportsCloning != true
    val explanation=listOfNotNull(
        engine.reason?.takeIf {it.isNotBlank()}, engine.hint?.takeIf {it.isNotBlank()},
        if(incompatible) text("mobile.speak.engine_no_cloning") else null,
        if(!engine.available && engine.reason.isNullOrBlank()) text("mobile.speak.engine_unavailable") else null
    ).joinToString("\n").ifBlank {null}
    Choice(engine.id, engine.displayName.ifBlank { engine.id }, engine.available && !incompatible, explanation)
}
fun initialEngine(family: EngineFamily, choices: List<Choice>): String = choices.firstOrNull { it.id == family.active && it.enabled }?.id
    ?: choices.firstOrNull { it.enabled }?.id.orEmpty()

fun Readiness.guidance(): Pair<String, Map<String, Any>> {
    val missing = missing
    val model = missing?.recommended
    val size = model?.sizeGb
    if(missing?.error == "asr_model_missing") {
        val name = model?.label?.takeIf { it.isNotBlank() } ?: missing.missingRepoId
        if(name != null) return if(size != null) "mobile.dictate.install_model_size" to mapOf("model" to name, "size" to size)
            else "mobile.dictate.install_model" to mapOf("model" to name)
    }
    if(!missing?.message.isNullOrBlank()) return "mobile.dictate.not_ready" to mapOf("reason" to missing!!.message!!)
    return "mobile.dictate.setup" to emptyMap()
}

fun languageCode(name:String):String? {
    return Locale.getAvailableLocales().filter {it.language.isNotBlank()}.firstOrNull {
        it.getDisplayLanguage(Locale.ENGLISH).equals(name,true) || it.toLanguageTag().equals(name,true)
    }?.language ?: when(name.lowercase()) {"chinese (simplified)","mandarin chinese","mandarin" -> "zh-CN";"chinese (traditional)" -> "zh-TW";else -> null}
}


fun paletteChoices(l: L10n): List<Pair<String,String>> = VSTokens.palettes.map {
    it.id to if(it.id=="default") l.t("themeAppearance.default") else it.label
}

/** M1 offers an engine preset or an existing profile, never implicit source cloning. */
fun dubVoiceChoices(profiles: List<Profile>, defaultLabel: String): List<Pair<String, String>> =
    listOf("" to defaultLabel) + profiles.map { it.id to it.name }
