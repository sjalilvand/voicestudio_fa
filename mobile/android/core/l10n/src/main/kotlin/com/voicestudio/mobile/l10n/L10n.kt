package com.voicestudio.mobile.l10n

import android.content.Context
import kotlinx.serialization.json.*
import java.util.Locale

class L10n(private val catalogs: Map<String, JsonObject>, val locale: String) {
    fun t(key: String, params: Map<String, Any> = emptyMap()): String {
        val tag = locale.replace('_', '-')
        val chain = listOf(tag, tag.substringBefore('-'), "en").distinct()
        val count = (params["count"] as? Number)?.toDouble()
        fun pluralFor(language: String): String? = if (count != null) {
            // i18next v4/CLDR categories for the desktop's 21 supported locales.
            val n = count.toLong(); val whole = n.toDouble() == count
            val mod10 = n % 10; val mod100 = n % 100
            when(language.substringBefore('-')) {
                "ar" -> when { count == 0.0 -> "zero"; count == 1.0 -> "one"; count == 2.0 -> "two"; whole && mod100 in 3..10 -> "few"; whole && mod100 in 11..99 -> "many"; else -> "other" }
                "ru", "uk" -> when { whole && mod10 == 1L && mod100 != 11L -> "one"; whole && mod10 in 2..4 && mod100 !in 12..14 -> "few"; whole && (mod10 == 0L || mod10 in 5..9 || mod100 in 11..14) -> "many"; else -> "other" }
                "pl" -> when { count == 1.0 -> "one"; whole && mod10 in 2..4 && mod100 !in 12..14 -> "few"; whole -> "many"; else -> "other" }
                "fr", "pt" -> if(n in 0..1) "one" else "other"
                "hi" -> if(n == 0L || count == 1.0) "one" else "other"
                "zh", "ja", "ko", "th", "vi", "id" -> "other"
                else -> if(count == 1.0) "one" else "other"
            }
        } else null
        val template = chain.firstNotNullOfOrNull { candidate ->
            val plural=pluralFor(candidate)
            val catalog = catalogs[candidate] ?: catalogs.entries.firstOrNull { it.key.equals(candidate, true) }?.value
            (if(plural != null) lookup(catalog, "${key}_$plural") ?: lookup(catalog, "${key}_other") else null) ?: lookup(catalog, key)
        } ?: key
        return PLACEHOLDER.replace(template) { match -> params[match.groupValues[1]]?.toString() ?: match.value }
    }
    fun has(key: String) = lookup(catalogs["en"], key) != null || lookup(catalogs["en"], "${key}_other") != null
    companion object {
        // Escape both braces: Android's ICU regex rejects a bare `}` that the
        // JVM (and so Robolectric) accepts, which crashed the app on launch.
        private val PLACEHOLDER = Regex("""\{\{\s*([^{}]+?)\s*\}\}""")
        val languages = listOf("en", "zh-CN", "es", "fr", "de", "ja", "pt", "it", "ru", "ko", "hi", "tr", "pl", "nl", "sv", "th", "vi", "id", "uk", "ar", "zh-TW")
        private fun lookup(obj: JsonObject?, key: String): String? {
            var node: JsonElement? = obj
            for(part in key.split('.')) node = (node as? JsonObject)?.get(part) ?: return null
            return (node as? JsonPrimitive)?.contentOrNull
        }
        private fun merge(a: JsonObject, b: JsonObject): JsonObject = JsonObject(a.toMutableMap().apply {
            b.forEach { (key, value) -> this[key] = if(value is JsonObject && this[key] is JsonObject) merge(this[key] as JsonObject, value) else value }
        })
        fun load(context: Context, locale: String = Locale.getDefault().toLanguageTag()): L10n {
            val assets = context.assets
            val catalogs = assets.list("locales").orEmpty().filter { it.endsWith(".json") }.associate { name ->
                name.removeSuffix(".json") to assets.open("locales/$name").bufferedReader().use { Json.parseToJsonElement(it.readText()).jsonObject }
            }.toMutableMap()
            // Shared defaults first, this platform's additions last. Build assets
            // can include the other platform's concurrently developed additions.
            val additions = assets.list("").orEmpty().filter { it.startsWith("strings") && it.endsWith(".en.json") }
                .sortedWith(compareBy<String> { when(it) { "strings.mobile.en.json" -> 0; "strings.android-additions.en.json" -> 2; else -> 1 } }.thenBy { it })
            for(name in additions) {
                val additional = assets.open(name).bufferedReader().use { Json.parseToJsonElement(it.readText()).jsonObject }
                catalogs["en"] = merge(catalogs["en"] ?: JsonObject(emptyMap()), additional)
            }
            return L10n(catalogs, locale)
        }
    }
}
