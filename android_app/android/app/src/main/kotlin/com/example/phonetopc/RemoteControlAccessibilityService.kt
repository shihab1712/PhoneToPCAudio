package com.example.phonetopc

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.util.DisplayMetrics
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import kotlin.math.roundToInt

class RemoteControlAccessibilityService : AccessibilityService() {
    companion object {
        @Volatile var activeService: RemoteControlAccessibilityService? = null
            private set
    }

    override fun onServiceConnected() {
        super.onServiceConnected()
        activeService = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    fun dispatchNormalizedGesture(points: List<Pair<Float, Float>>, durationMs: Int): Boolean {
        if (points.isEmpty()) return false
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        (getSystemService(WINDOW_SERVICE) as WindowManager).defaultDisplay.getRealMetrics(metrics)
        val path = Path()
        points.forEachIndexed { index, point ->
            val x = (point.first.coerceIn(0f, 1f) * (metrics.widthPixels - 1)).roundToInt().toFloat()
            val y = (point.second.coerceIn(0f, 1f) * (metrics.heightPixels - 1)).roundToInt().toFloat()
            if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        val stroke = GestureDescription.StrokeDescription(
            path,
            0,
            durationMs.coerceIn(50, 2_000).toLong(),
        )
        return dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), null, null)
    }

    override fun onDestroy() {
        if (activeService === this) activeService = null
        super.onDestroy()
    }
}
