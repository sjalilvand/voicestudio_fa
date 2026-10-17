package com.voicestudio.mobile.l10n

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class L10nTest {
    private fun obj(value:String)=Json.parseToJsonElement(value).jsonObject
    @Test fun nestedInterpolationPluralAndFallback() {
        val catalogs=mapOf("en" to obj("""{"greeting":"Hello {{name}}", "count_one":"{{count}} item", "count_other":"{{count}} items", "nested":{"label":"English"}}"""),"fr" to obj("""{"nested":{"label":"French"}}"""),"fr-CA" to obj("""{"greeting":"Bonjour {{name}}"}"""))
        val l=L10n(catalogs,"fr-CA")
        assertEquals("Bonjour Ada",l.t("greeting",mapOf("name" to "Ada")))
        assertEquals("French",l.t("nested.label"))
        assertEquals("1 item",l.t("count",mapOf("count" to 1)))
        assertEquals("3 items",l.t("count",mapOf("count" to 3)))
        assertEquals("missing.key",l.t("missing.key"))
        assertEquals("Hello Ada",L10n(catalogs,"de-DE").t("greeting",mapOf("name" to "Ada")))
    }
    @Test fun pluralCategoriesAndCaseInsensitiveLocale() {
        val l=L10n(mapOf("en" to obj("""{"count_one":"one","count_other":"other"}"""),"ru" to obj("""{"count_one":"one","count_few":"few","count_many":"many","count_other":"other"}""")),"ru-RU")
        assertEquals("few",l.t("count",mapOf("count" to 2)));assertEquals("many",l.t("count",mapOf("count" to 11)))
    }
}
