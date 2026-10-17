package com.voicestudio.mobile.features

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.path
import androidx.compose.ui.unit.dp
import com.voicestudio.mobile.designsystem.*

object VSIcons {
    private fun glyph(name: String, draw: androidx.compose.ui.graphics.vector.PathBuilder.()->Unit): ImageVector =
        ImageVector.Builder(name,24.dp,24.dp,24f,24f).path(fill=SolidColor(Color(VSTheme.roles("default",true).getValue("text"))),pathBuilder=draw).build()
    val Qr by lazy {glyph("QR") {
        moveTo(3f,3f);lineTo(10f,3f);lineTo(10f,10f);lineTo(3f,10f);close()
        moveTo(14f,3f);lineTo(21f,3f);lineTo(21f,10f);lineTo(14f,10f);close()
        moveTo(3f,14f);lineTo(10f,14f);lineTo(10f,21f);lineTo(3f,21f);close()
        moveTo(14f,14f);lineTo(17f,14f);lineTo(17f,17f);lineTo(21f,17f);lineTo(21f,21f);lineTo(14f,21f);close()
    }}
    val Mic by lazy {glyph("Mic") {
        moveTo(9f,3f);lineTo(15f,3f);lineTo(15f,14f);lineTo(9f,14f);close()
        moveTo(6f,11f);lineTo(8f,11f);lineTo(8f,16f);lineTo(16f,16f);lineTo(16f,11f);lineTo(18f,11f);lineTo(18f,18f);lineTo(13f,18f);lineTo(13f,21f);lineTo(11f,21f);lineTo(11f,18f);lineTo(6f,18f);close()
    }}
    val Copy by lazy {glyph("Copy") {
        moveTo(4f,3f);lineTo(16f,3f);lineTo(16f,5f);lineTo(6f,5f);lineTo(6f,17f);lineTo(4f,17f);close()
        moveTo(8f,7f);lineTo(20f,7f);lineTo(20f,21f);lineTo(8f,21f);close()
    }}
    val Download: ImageVector by lazy {
        val size=VSTokens.SPACING_INSET
        ImageVector.Builder("Download",size.dp,size.dp,size,size).path(fill=SolidColor(Color(VSTheme.roles("default",true).getValue("text")))) {
            moveTo(size*5/12,size/8);lineTo(size*7/12,size/8);lineTo(size*7/12,size/2)
            lineTo(size*3/4,size/2);lineTo(size/2,size*3/4);lineTo(size/4,size/2);lineTo(size*5/12,size/2);close()
            moveTo(size/4,size*7/8);lineTo(size*3/4,size*7/8);lineTo(size*3/4,size);lineTo(size/4,size);close()
        }.build()
    }
    // Material's core icon artifact omits Pause; keep this simple glyph local.
    val Pause: ImageVector by lazy {
        val size=VSTokens.SPACING_INSET
        ImageVector.Builder("Pause",size.dp,size.dp,size,size).path(fill=SolidColor(Color(VSTheme.roles("default",true).getValue("text")))) {
            moveTo(size/4,size/4);lineTo(size*5/12,size/4);lineTo(size*5/12,size*3/4);lineTo(size/4,size*3/4);close()
            moveTo(size*7/12,size/4);lineTo(size*3/4,size/4);lineTo(size*3/4,size*3/4);lineTo(size*7/12,size*3/4);close()
        }.build()
    }
}
