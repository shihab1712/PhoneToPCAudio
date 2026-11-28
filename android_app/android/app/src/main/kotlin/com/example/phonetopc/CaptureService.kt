package com.example.phonetopc

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.os.Process
import android.os.SystemClock
import android.util.Log
import android.util.DisplayMetrics
import java.io.ByteArrayOutputStream
import kotlin.concurrent.thread

class CaptureService : Service() {
    companion object {
        @Volatile var eventSink: io.flutter.plugin.common.EventChannel.EventSink? = null
        @Volatile private var activeInstance: CaptureService? = null
        @Volatile private var requestedPhoneMute = false

        fun setPhoneMediaMuted(muted: Boolean): Boolean {
            requestedPhoneMute = muted
            return activeInstance?.applyPhoneMediaMute(muted) ?: true
        }

        private const val TAG = "PhoneToPcCapture"
        // 10 ms at 48 kHz, stereo, signed 16-bit PCM.
        private const val FRAME_BYTES = 1_920
        private const val DEFAULT_VIDEO_MAX_WIDTH = 720
        private const val DEFAULT_VIDEO_INTERVAL_MS = 33L
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    @Volatile private var running = false
    private var worker: Thread? = null
    private var projection: MediaProjection? = null
    @Volatile private var audioRecord: AudioRecord? = null
    private var videoThread: HandlerThread? = null
    private var imageReader: ImageReader? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var videoDisplayManager: DisplayManager? = null
    private var videoDisplayListener: DisplayManager.DisplayListener? = null
    private var videoHandler: Handler? = null
    private var videoWidth = 0
    private var videoHeight = 0
    private var videoDensityDpi = 0
    private var videoMaxWidth = DEFAULT_VIDEO_MAX_WIDTH
    private var videoIntervalMs = DEFAULT_VIDEO_INTERVAL_MS
    private var videoJpegQuality = 48
    private var videoPixels: IntArray? = null
    private var videoBitmap: Bitmap? = null
    private var videoRgbaBytes: ByteArray? = null
    private val videoJpegOutput = ByteArrayOutputStream()
    private val videoSendLock = Any()
    private var pendingVideoFrame: ByteArray? = null
    private var videoSendScheduled = false
    private var includeVideo = false
    private var lastVideoFrameAt = 0L
    private var phoneMediaMuted = false
    private var previousMusicVolume: Int? = null

    override fun onBind(intent: Intent?): IBinder? = null

    private fun sendAudio(data: ByteArray) {
        val sink = eventSink ?: return
        val payload: Any = if (includeVideo) mapOf("type" to "audio", "data" to data) else data
        mainHandler.post { if (eventSink === sink) sink.success(payload) }
    }

    private fun sendVideo(data: ByteArray) {
        val sink = eventSink ?: return
        val shouldPost = synchronized(videoSendLock) {
            pendingVideoFrame = data
            if (videoSendScheduled) false else {
                videoSendScheduled = true
                true
            }
        }
        if (!shouldPost) return
        mainHandler.post {
            val newestFrame = synchronized(videoSendLock) {
                videoSendScheduled = false
                pendingVideoFrame.also { pendingVideoFrame = null }
            }
            if (newestFrame != null && eventSink === sink && running) {
                sink.success(mapOf("type" to "video", "data" to newestFrame))
            }
        }
    }

    @Synchronized
    private fun applyPhoneMediaMute(muted: Boolean): Boolean {
        if (muted == phoneMediaMuted) return true
        val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return try {
            if (muted) {
                if (audioManager.isVolumeFixed) return false
                val currentVolume = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC)
                previousMusicVolume = currentVolume
                audioManager.setStreamVolume(
                    AudioManager.STREAM_MUSIC,
                    0,
                    AudioManager.FLAG_REMOVE_SOUND_AND_VIBRATE,
                )
                phoneMediaMuted = audioManager.getStreamVolume(AudioManager.STREAM_MUSIC) == 0
                if (!phoneMediaMuted) previousMusicVolume = null
                phoneMediaMuted
            } else {
                val previousVolume = previousMusicVolume
                if (previousVolume != null && audioManager.getStreamVolume(AudioManager.STREAM_MUSIC) == 0) {
                    audioManager.setStreamVolume(
                        AudioManager.STREAM_MUSIC,
                        previousVolume,
                        AudioManager.FLAG_REMOVE_SOUND_AND_VIBRATE,
                    )
                }
                phoneMediaMuted = false
                previousMusicVolume = null
                true
            }
        } catch (error: SecurityException) {
            Log.w(TAG, "Could not change phone media volume", error)
            false
        }
    }

    private fun sendCaptureError(error: Exception) {
        Log.e(TAG, "Playback capture failed", error)
        val sink = eventSink ?: return
        mainHandler.post {
            if (eventSink === sink) sink.error("CAPTURE", error.message ?: error.javaClass.simpleName, null)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        activeInstance = this
        if (running) {
            applyPhoneMediaMute(requestedPhoneMute)
            return START_NOT_STICKY
        }
        applyPhoneMediaMute(requestedPhoneMute)
        includeVideo = intent?.getBooleanExtra("includeVideo", false) ?: false
        videoMaxWidth = intent?.getIntExtra("videoMaxWidth", DEFAULT_VIDEO_MAX_WIDTH)
            ?.coerceIn(360, 1080) ?: DEFAULT_VIDEO_MAX_WIDTH
        videoIntervalMs = intent?.getIntExtra("videoIntervalMs", DEFAULT_VIDEO_INTERVAL_MS.toInt())
            ?.coerceIn(16, 500)?.toLong() ?: DEFAULT_VIDEO_INTERVAL_MS
        videoJpegQuality = intent?.getIntExtra("videoJpegQuality", 48)?.coerceIn(35, 85) ?: 48
        val channel = "phone_to_pc_capture"
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= 26) manager.createNotificationChannel(
            NotificationChannel(channel, "Phone streaming", NotificationManager.IMPORTANCE_LOW),
        )
        val title = if (includeVideo) "Streaming phone audio and screen" else "Streaming phone audio"
        val notification: Notification = if (Build.VERSION.SDK_INT >= 26) {
            Notification.Builder(this, channel).setContentTitle(title)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now).build()
        } else {
            Notification.Builder(this).setContentTitle(title)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now).build()
        }
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, notification, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else startForeground(1, notification)

        val code = intent?.getIntExtra("resultCode", 0) ?: 0
        val data = if (Build.VERSION.SDK_INT >= 33) {
            intent?.getParcelableExtra("projectionData", Intent::class.java)
        } else @Suppress("DEPRECATION") intent?.getParcelableExtra("projectionData")
        if (data == null) {
            stopSelf()
            return START_NOT_STICKY
        }

        val managerProjection = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projection = managerProjection.getMediaProjection(code, data)
        projection?.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                running = false
                stopSelf()
            }

            override fun onCapturedContentResize(width: Int, height: Int) {
                if (includeVideo && virtualDisplay != null && width > 0 && height > 0) {
                    resizeVideoCapture(width, height)
                }
            }
        }, mainHandler)
        running = true
        worker = thread(name = "PlaybackCapture") { captureLoop() }
        if (includeVideo) startVideoCapture()
        return START_NOT_STICKY
    }

    private fun startVideoCapture() {
        try {
            val thread = HandlerThread("PhoneScreenCapture").also { it.start() }
            videoThread = thread
            videoHandler = Handler(thread.looper)
            val metrics = DisplayMetrics()
            val manager = getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
            videoDisplayManager = manager
            @Suppress("DEPRECATION")
            manager.getDisplay(android.view.Display.DEFAULT_DISPLAY).getRealMetrics(metrics)
            resizeVideoCapture(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi, force = true)
            val listener = object : DisplayManager.DisplayListener {
                override fun onDisplayAdded(displayId: Int) = Unit
                override fun onDisplayRemoved(displayId: Int) = Unit
                override fun onDisplayChanged(displayId: Int) {
                    if (displayId != android.view.Display.DEFAULT_DISPLAY) return
                    val changedMetrics = DisplayMetrics()
                    @Suppress("DEPRECATION")
                    manager.getDisplay(displayId)?.getRealMetrics(changedMetrics)
                    if (changedMetrics.widthPixels > 0 && changedMetrics.heightPixels > 0) {
                        resizeVideoCapture(
                            changedMetrics.widthPixels,
                            changedMetrics.heightPixels,
                            changedMetrics.densityDpi,
                        )
                    }
                }
            }
            videoDisplayListener = listener
            manager.registerDisplayListener(listener, mainHandler)
        } catch (error: Exception) {
            Log.e(TAG, "Could not start screen capture", error)
            sendCaptureError(error)
        }
    }

    private fun resizeVideoCapture(sourceWidth: Int, sourceHeight: Int, densityDpi: Int = resources.displayMetrics.densityDpi, force: Boolean = false) {
        try {
            val scale = minOf(1f, videoMaxWidth.toFloat() / sourceWidth.toFloat())
            val width = ((sourceWidth * scale).toInt().coerceAtLeast(2) / 2) * 2
            val height = ((sourceHeight * scale).toInt().coerceAtLeast(2) / 2) * 2
            val density = (densityDpi * scale).toInt().coerceAtLeast(1)
            if (!force && width == videoWidth && height == videoHeight && density == videoDensityDpi) return
            val handler = videoHandler ?: return
            val reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2)
            reader.setOnImageAvailableListener({ source ->
                var image: Image? = null
                try {
                    image = source.acquireLatestImage() ?: return@setOnImageAvailableListener
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastVideoFrameAt < videoIntervalMs) return@setOnImageAvailableListener
                    lastVideoFrameAt = now
                    val jpeg = imageToJpeg(image)
                    if (jpeg.isNotEmpty()) sendVideo(jpeg)
                } catch (error: Exception) {
                    Log.w(TAG, "Could not encode screen frame", error)
                } finally {
                    image?.close()
                }
            }, handler)
            val existingDisplay = virtualDisplay
            if (existingDisplay == null) {
                virtualDisplay = projection?.createVirtualDisplay(
                    "PhoneToPcScreen",
                    width,
                    height,
                    density,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    reader.surface,
                    null,
                    handler,
                )
                if (virtualDisplay == null) {
                    reader.close()
                    throw IllegalStateException("Android could not create a screen capture display")
                }
            } else {
                existingDisplay.resize(width, height, density)
                existingDisplay.surface = reader.surface
            }
            val previousReader = imageReader
            imageReader = reader
            videoWidth = width
            videoHeight = height
            videoDensityDpi = density
            previousReader?.setOnImageAvailableListener(null, null)
            previousReader?.close()
        } catch (error: Exception) {
            Log.e(TAG, "Could not resize screen capture", error)
            sendCaptureError(error)
        }
    }

    private fun imageToJpeg(image: Image): ByteArray {
        val width = image.width
        val height = image.height
        val plane = image.planes.firstOrNull() ?: return ByteArray(0)
        val buffer = plane.buffer.duplicate()
        val pixelStride = plane.pixelStride
        val rowStride = plane.rowStride
        val byteCount = buffer.remaining()
        val rgbaBytes = videoRgbaBytes?.takeIf { it.size == byteCount }
            ?: ByteArray(byteCount).also { videoRgbaBytes = it }
        buffer.get(rgbaBytes)
        val pixels = videoPixels?.takeIf { it.size == width * height }
            ?: IntArray(width * height).also { videoPixels = it }
        for (y in 0 until height) {
            val row = y * rowStride
            for (x in 0 until width) {
                val offset = row + x * pixelStride
                val red = rgbaBytes[offset].toInt() and 0xff
                val green = rgbaBytes[offset + 1].toInt() and 0xff
                val blue = rgbaBytes[offset + 2].toInt() and 0xff
                val alpha = rgbaBytes[offset + 3].toInt() and 0xff
                pixels[y * width + x] = (alpha shl 24) or (red shl 16) or (green shl 8) or blue
            }
        }
        val bitmap = videoBitmap?.takeIf { !it.isRecycled && it.width == width && it.height == height }
            ?: Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888).also { videoBitmap = it }
        bitmap.setPixels(pixels, 0, width, 0, 0, width, height)
        videoJpegOutput.reset()
        bitmap.compress(Bitmap.CompressFormat.JPEG, videoJpegQuality, videoJpegOutput)
        return videoJpegOutput.toByteArray()
    }

    private fun captureLoop() {
        Process.setThreadPriority(Process.THREAD_PRIORITY_AUDIO)
        var record: AudioRecord? = null
        try {
            val rate = 48_000
            val mask = AudioFormat.CHANNEL_IN_STEREO
            val format = AudioFormat.ENCODING_PCM_16BIT
            val size = AudioRecord.getMinBufferSize(rate, mask, format).coerceAtLeast(FRAME_BYTES) * 2
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
            val buffer = ByteArray(FRAME_BYTES)
            while (running) {
                val count = activeRecord.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
                if (count > 0) sendAudio(if (count == buffer.size) buffer.copyOf() else buffer.copyOf(count))
            }
        } catch (error: Exception) {
            if (running) sendCaptureError(error)
        } finally {
            try { record?.stop() } catch (_: Exception) {}
            record?.release()
            audioRecord = null
        }
    }

    override fun onDestroy() {
        applyPhoneMediaMute(false)
        requestedPhoneMute = false
        if (activeInstance === this) activeInstance = null
        running = false
        try { audioRecord?.stop() } catch (_: Exception) {}
        worker?.interrupt()
        virtualDisplay?.release()
        virtualDisplay = null
        imageReader?.setOnImageAvailableListener(null, null)
        imageReader?.close()
        imageReader = null
        videoDisplayListener?.let { listener -> videoDisplayManager?.unregisterDisplayListener(listener) }
        videoDisplayListener = null
        videoDisplayManager = null
        videoBitmap = null
        videoPixels = null
        videoRgbaBytes = null
        videoThread?.quitSafely()
        videoThread = null
        projection?.stop()
        projection = null
        super.onDestroy()
    }
}
