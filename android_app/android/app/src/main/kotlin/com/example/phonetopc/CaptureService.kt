package com.example.phonetopc

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.util.Log
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioAttributes
import kotlin.concurrent.thread

class CaptureService : Service() {
    companion object {
        @Volatile var eventSink: io.flutter.plugin.common.EventChannel.EventSink? = null
        private const val TAG = "PhoneToPcCapture"
    }
    private val mainHandler = Handler(Looper.getMainLooper())
    @Volatile private var running = false
    private var worker: Thread? = null
    private var projection: MediaProjection? = null
    @Volatile private var audioRecord: AudioRecord? = null
    override fun onBind(intent: Intent?): IBinder? = null

    private fun sendAudio(data: ByteArray) {
        val sink = eventSink ?: return
        mainHandler.post { if (eventSink === sink) sink.success(data) }
    }

    private fun sendCaptureError(error: Exception) {
        Log.e(TAG, "Playback capture failed", error)
        val sink = eventSink ?: return
        mainHandler.post {
            if (eventSink === sink) sink.error("CAPTURE", error.message ?: error.javaClass.simpleName, null)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (running) return START_NOT_STICKY
        val channel = "phone_to_pc_capture"
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(NotificationChannel(channel, "Audio streaming", NotificationManager.IMPORTANCE_LOW))
        val notification: Notification = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, channel).setContentTitle("Streaming phone audio").setSmallIcon(android.R.drawable.ic_btn_speak_now).build() else Notification.Builder(this).setContentTitle("Streaming phone audio").setSmallIcon(android.R.drawable.ic_btn_speak_now).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, notification, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION) else startForeground(1, notification)
        val code = intent?.getIntExtra("resultCode", 0) ?: 0
        val data = if (Build.VERSION.SDK_INT >= 33) intent?.getParcelableExtra("projectionData", Intent::class.java) else @Suppress("DEPRECATION") intent?.getParcelableExtra("projectionData")
        if (data == null) { stopSelf(); return START_NOT_STICKY }
        val managerProjection = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projection = managerProjection.getMediaProjection(code, data)
        projection?.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() { running = false; stopSelf() }
        }, Handler(Looper.getMainLooper()))
        running = true
        worker = thread(name = "PlaybackCapture") { captureLoop() }
        return START_NOT_STICKY
    }
    private fun captureLoop() {
        Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
        var record: AudioRecord? = null
        try {
            val rate = 48_000
            val mask = AudioFormat.CHANNEL_IN_STEREO
            val format = AudioFormat.ENCODING_PCM_16BIT
            val size = AudioRecord.getMinBufferSize(rate, mask, format).coerceAtLeast(3_840) * 2
            val config = AudioPlaybackCaptureConfiguration.Builder(projection!!)
                .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
                .addMatchingUsage(AudioAttributes.USAGE_GAME)
                .build()
            val activeRecord = AudioRecord.Builder()
                .setAudioFormat(AudioFormat.Builder().setEncoding(format).setSampleRate(rate).setChannelMask(mask).build())
                .setBufferSizeInBytes(size)
                .setAudioPlaybackCaptureConfig(config)
                .build()
            record = activeRecord
            audioRecord = activeRecord
            activeRecord.startRecording()
            val buffer = ByteArray(3_840)
            while (running) {
                val count = activeRecord.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
                if (count > 0) sendAudio(if (count == buffer.size) buffer.copyOf() else buffer.copyOf(count))
            }
        } catch (error: Exception) {
            sendCaptureError(error)
        } finally {
            try { record?.stop() } catch (_: Exception) {}
            record?.release()
            audioRecord = null
        }
    }
    override fun onDestroy() { running = false; try { audioRecord?.stop() } catch (_: Exception) {}; worker?.interrupt(); projection?.stop(); projection = null; super.onDestroy() }
}
