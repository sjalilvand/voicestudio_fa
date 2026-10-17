package com.voicestudio.mobile.network

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** /engines/translation has a loose OpenAPI schema; fields follow engines.py. */
@Serializable data class TranslationEngine(
    val id: String,
    @SerialName("display_name") val displayName: String = "",
    val category: String = "",
    val installed: Boolean = false,
    val ready: Boolean = false,
) {
    fun requireReady(): TranslationEngine {
        if(id.isBlank() || !installed || !ready || category !in setOf("offline", "online", "llm"))
            throw ClientFailure("mobile.dub.translation_setup")
        return this
    }
    fun authorize(onlineConfirmed: Boolean = false): TranslationAuthorization? {
        requireReady()
        if(category == "online" && !onlineConfirmed) return null
        return TranslationAuthorization(id, category, category == "online" && onlineConfirmed)
    }
}
@Serializable data class TranslationEngines(val active: String = "", val engines: List<TranslationEngine> = emptyList()) {
    fun activeEngine(): TranslationEngine = engines.firstOrNull { it.id == active && active.isNotBlank() }?.requireReady()
        ?: throw ClientFailure("mobile.dub.translation_setup")
}

/** Job-scoped approval, never a preference or an implicit provider fallback. */
class TranslationAuthorization internal constructor(val provider: String, val category: String, val onlineConfirmed: Boolean)
