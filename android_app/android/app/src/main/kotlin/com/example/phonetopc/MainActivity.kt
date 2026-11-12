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
