package com.example.phonetopc

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val requestCode = 4301
    private val audioPermissionRequest = 4302
    private var pending: MethodChannel.Result? = null
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
                    if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                        requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), audioPermissionRequest)
                    } else requestCaptureConsent()
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
        startForegroundService(Intent(this, CaptureService::class.java).putExtra("resultCode", resultCode).putExtra("projectionData", data))
        callback.success(null)
    }
}
