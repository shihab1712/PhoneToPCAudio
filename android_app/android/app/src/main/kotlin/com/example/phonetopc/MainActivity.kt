package com.example.phonetopc

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.provider.Settings
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val requestCode = 4301
    private val audioPermissionRequest = 4302
    private var pending: MethodChannel.Result? = null
    private var pendingIncludeVideo = false
    override fun configureFlutterEngine(engine: FlutterEngine) {
        super.configureFlutterEngine(engine)
        MethodChannel(engine.dartExecutor.binaryMessenger, "phonetopc/capture").setMethodCallHandler { call, result ->
            when (call.method) {
                "getDeviceName" -> {
                    val manufacturer = android.os.Build.MANUFACTURER.orEmpty().trim()
                    val model = android.os.Build.MODEL.orEmpty().trim()
                    val deviceName = listOf(manufacturer, model)
                        .filter { it.isNotBlank() }
                        .distinct()
                        .joinToString(" ")
                    result.success(deviceName.ifBlank { "Android device" })
                }
                "startCapture" -> {
                    if (pending != null) { result.error("BUSY", "Capture request already active", null); return@setMethodCallHandler }
                    pending = result
                    pendingIncludeVideo = call.argument<Boolean>("includeVideo") ?: false
                    val quality = call.argument<String>("videoQuality") ?: "balanced"
                    val frameRate = call.argument<String>("videoFrameRate") ?: "30"
                    val (maxWidth, jpegQuality) = when (quality) {
                        "low" -> 480 to 45
                        "high" -> 960 to 55
                        else -> 720 to 48
                    }
                    val intervalMs = if (frameRate == "60") 16 else 33
                    getPreferences(MODE_PRIVATE).edit()
                        .putInt("video_max_width", maxWidth)
                        .putInt("video_interval_ms", intervalMs)
                        .putInt("video_jpeg_quality", jpegQuality)
                        .apply()
                    if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                        requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), audioPermissionRequest)
                    } else requestCaptureConsent()
                }
                "setPhoneMuted" -> {
                    val muted = call.argument<Boolean>("muted") ?: false
                    result.success(CaptureService.setPhoneMediaMuted(muted))
                }
                "openMouseControlSettings" -> {
                    startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                    result.success(null)
                }
                "dispatchMouseGesture" -> {
                    val rawPoints = call.argument<List<Any>>("points").orEmpty()
                    val points = rawPoints.mapNotNull { raw ->
                        val pair = raw as? List<*> ?: return@mapNotNull null
                        val x = pair.getOrNull(0) as? Number ?: return@mapNotNull null
                        val y = pair.getOrNull(1) as? Number ?: return@mapNotNull null
                        x.toFloat() to y.toFloat()
                    }
                    val duration = call.argument<Int>("durationMs") ?: 120
                    val service = RemoteControlAccessibilityService.activeService
                    result.success(service?.dispatchNormalizedGesture(points, duration) == true)
                }
                "stopCapture" -> { stopService(Intent(this, CaptureService::class.java)); result.success(null) }
                else -> result.notImplemented()
            }
        }
        MethodChannel(engine.dartExecutor.binaryMessenger, "phonetopc/settings").setMethodCallHandler { call, result ->
            val preferences = getSharedPreferences("phone_to_pc_settings", MODE_PRIVATE)
            when (call.method) {
                "getThemeMode" -> result.success(preferences.getString("theme_mode", "system"))
                "setThemeMode" -> {
                    val mode = call.argument<String>("themeMode")
                    if (mode !in setOf("system", "light", "dark")) {
                        result.error("INVALID_THEME", "Theme must be system, light, or dark", null)
                    } else {
                        preferences.edit().putString("theme_mode", mode).apply()
                        result.success(null)
                    }
                }
                "getConnectionSettings" -> result.success(
                    mapOf(
                        "host" to preferences.getString("pc_host", ""),
                        "port" to preferences.getString("pc_port", "8765"),
                        "mode" to preferences.getString("connection_mode", "wifi"),
                        "wifiHost" to preferences.getString("wifi_host", ""),
                    ),
                )
                "setConnectionSettings" -> {
                    val host = call.argument<String>("host") ?: ""
                    val port = call.argument<String>("port") ?: "8765"
                    val mode = call.argument<String>("mode") ?: "wifi"
                    val wifiHost = call.argument<String>("wifiHost") ?: ""
                    preferences.edit()
                        .putString("pc_host", host)
                        .putString("pc_port", port)
                        .putString("connection_mode", mode)
                        .putString("wifi_host", wifiHost)
                        .apply()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
        EventChannel(engine.dartExecutor.binaryMessenger, "phonetopc/audio").setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(arguments: Any?, events: EventChannel.EventSink?) { CaptureService.eventSink = events }
            override fun onCancel(arguments: Any?) { CaptureService.eventSink = null }
        })
    }
    private fun requestCaptureConsent() {
        val manager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        startActivityForResult(manager.createScreenCaptureIntent(), requestCode)
    }
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != audioPermissionRequest) return
        val callback = pending ?: return
        if (grantResults.firstOrNull() == android.content.pm.PackageManager.PERMISSION_GRANTED) requestCaptureConsent()
        else { pending = null; callback.error("DENIED", "Microphone permission is needed for playback capture", null) }
    }
    @Deprecated("Deprecated in Android API")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != this.requestCode) return
        val callback = pending ?: return
        pending = null
        if (resultCode != Activity.RESULT_OK || data == null) { callback.error("DENIED", "Playback capture permission was not granted", null); return }
        startForegroundService(
            Intent(this, CaptureService::class.java)
                .putExtra("resultCode", resultCode)
                .putExtra("projectionData", data)
                .putExtra("includeVideo", pendingIncludeVideo)
                .putExtra("videoMaxWidth", getPreferences(MODE_PRIVATE).getInt("video_max_width", 720))
                .putExtra("videoIntervalMs", getPreferences(MODE_PRIVATE).getInt("video_interval_ms", 33))
                .putExtra("videoJpegQuality", getPreferences(MODE_PRIVATE).getInt("video_jpeg_quality", 48)),
        )
        callback.success(null)
    }
}
