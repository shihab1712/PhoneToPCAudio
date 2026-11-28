"""Shared WebSocket PCM receive and local playback logic."""

from array import array
from collections import deque
import asyncio
import sys
from threading import Lock

import sounddevice as sd
from websockets.exceptions import ConnectionClosed

RATE = 48_000
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_BYTES = 1_920  # 10 ms at 48 kHz, stereo, signed 16-bit PCM
VIDEO_PREFIX = b"PTP1V"
AUDIO_PREFIX = b"PTP1A"


class VolumeControl:
    """Thread-safe playback gain shared by the desktop UI and receiver loop."""

    def __init__(self, percent=100):
        self._lock = Lock()
        self._percent = max(0.0, min(100.0, float(percent)))

    def set_percent(self, percent):
        with self._lock:
            self._percent = max(0.0, min(100.0, float(percent)))

    def get_gain(self):
        with self._lock:
            return self._percent / 100.0


class AudioBufferControl:
    """Thread-safe target prebuffer duration used by stream playback."""

    def __init__(self, milliseconds=100):
        self._lock = Lock()
        self._milliseconds = max(0, min(500, int(milliseconds)))
        self._revision = 0

    def set_ms(self, milliseconds):
        with self._lock:
            value = max(0, min(500, int(milliseconds)))
            if value != self._milliseconds:
                self._milliseconds = value
                self._revision += 1

    def snapshot(self):
        with self._lock:
            return self._milliseconds, self._revision

    def get_ms(self):
        with self._lock:
            return self._milliseconds


class OutputDeviceControl:
    """Thread-safe device selection shared with every active playback stream."""

    def __init__(self, device=None):
        self._lock = Lock()
        self._device = device
        self._revision = 0

    def set_device(self, device):
        with self._lock:
            if device != self._device:
                self._device = device
                self._revision += 1

    def snapshot(self):
        with self._lock:
            return self._device, self._revision


class PlaybackOutput:
    """Manage an output stream that can be switched without closing the phone connection."""

    def __init__(self, *, device, latency):
        self.latency = latency
        self._lock = Lock()
        self._stream = self._open(device)

    def _open(self, device):
        stream = sd.RawOutputStream(
            samplerate=RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=0,
            latency=self.latency,
            device=device,
        )
        stream.start()
        return stream

    def switch(self, device):
        replacement = self._open(device)
        with self._lock:
            previous = self._stream
            self._stream = replacement
            try:
                previous.stop()
            finally:
                previous.close()

    def write(self, data):
        with self._lock:
            self._stream.write(data)

    def close(self):
        with self._lock:
            if self._stream is not None:
                stream, self._stream = self._stream, None
                try:
                    stream.stop()
                finally:
                    stream.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _scale_pcm16le(data, gain):
    if gain >= 1.0:
        return data
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    for index, sample in enumerate(samples):
        samples[index] = max(-32768, min(32767, round(sample * gain)))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


async def receive_audio(
    websocket,
    *,
    output_device=None,
    output_device_control=None,
    volume_control=None,
    buffer_control=None,
    low_latency=False,
    on_event=None,
):
    """Receive PCM frames and play them to the selected Windows output."""
    def emit(name, value=None):
        if on_event is not None:
            on_event(name, value)

    if websocket.request.path != "/audio":
        await websocket.close(1008, "Use /audio")
        return

    peer = websocket.remote_address
    emit("websocket", websocket)
    emit("connected", peer)
    if output_device_control is not None:
        output_device, output_revision = output_device_control.snapshot()
    else:
        output_revision = 0
    failed_output_revision = None
    try:
        with PlaybackOutput(
            device=output_device,
            latency="low" if low_latency else "high",
        ) as output:
            frames = asyncio.Queue(maxsize=64)
            queued_ms = 0.0
            bytes_per_second = RATE * CHANNELS * SAMPLE_WIDTH

            async def read_frames():
                nonlocal queued_ms
                try:
                    async for message in websocket:
                        if not isinstance(message, bytes):
                            if isinstance(message, str) and message.startswith("DEVICE_NAME:"):
                                device_name = message.removeprefix("DEVICE_NAME:").strip()[:80]
                                if device_name:
                                    emit("device_name", device_name)
                                continue
                            if isinstance(message, str) and message.startswith("CONTROL_ERROR:"):
                                emit("control_error", message.removeprefix("CONTROL_ERROR:").strip())
                                continue
                            if isinstance(message, str) and message.startswith("PHONE_MUTE_RESULT:"):
                                emit("phone_mute_result", message.removeprefix("PHONE_MUTE_RESULT:").strip())
                                continue
                            emit("warning", "Ignored a non-binary message")
                            continue
                        if message.startswith(VIDEO_PREFIX):
                            jpeg = message[len(VIDEO_PREFIX):]
                            if jpeg:
                                emit("video_frame", jpeg)
                            continue
                        if message.startswith(AUDIO_PREFIX):
                            message = message[len(AUDIO_PREFIX):]
                        if len(message) % (CHANNELS * SAMPLE_WIDTH):
                            emit("warning", f"Ignored malformed PCM packet ({len(message)} bytes)")
                            continue
                        if not message:
                            continue
                        if volume_control is not None:
                            message = _scale_pcm16le(message, volume_control.get_gain())
                        duration_ms = len(message) * 1000.0 / bytes_per_second
                        await frames.put((message, duration_ms))
                        queued_ms += duration_ms
                except ConnectionClosed:
                    pass
                finally:
                    # Never block handler cleanup while the playback queue is full.
                    try:
                        frames.put_nowait(None)
                    except asyncio.QueueFull:
                        frames.get_nowait()
                        frames.task_done()
                        frames.put_nowait(None)

            async def measure_network_rtt():
                loop = asyncio.get_running_loop()
                while True:
                    started = loop.time()
                    try:
                        pong = await websocket.ping()
                        await asyncio.wait_for(pong, timeout=3.0)
                        emit("latency", (loop.time() - started) * 1000.0)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        emit("latency", None)
                    await asyncio.sleep(1.0)

            async def play_frames():
                nonlocal queued_ms, output_device, output_revision, failed_output_revision
                pending = deque()
                primed = False
                finished = False
                last_revision = -1

                async def take_frame():
                    nonlocal queued_ms, finished
                    item = await frames.get()
                    if item is None:
                        frames.task_done()
                        finished = True
                        return None
                    return item

                while True:
                    target_ms, revision = buffer_control.snapshot() if buffer_control is not None else (0, 0)
                    if revision != last_revision:
                        if target_ms > queued_ms:
                            primed = False
                        last_revision = revision

                    if not primed:
                        while queued_ms < target_ms and not finished:
                            item = await take_frame()
                            if item is None:
                                break
                            pending.append(item)
                        primed = True

                    if pending:
                        data, duration_ms = pending.popleft()
                    elif finished and frames.empty():
                        break
                    else:
                        item = await take_frame()
                        if item is None:
                            if not pending:
                                break
                            continue
                        data, duration_ms = item

                    selected_device, selected_revision = (
                        output_device_control.snapshot()
                        if output_device_control is not None
                        else (output_device, output_revision)
                    )
                    if selected_revision != output_revision and selected_revision != failed_output_revision:
                        try:
                            await asyncio.to_thread(output.switch, selected_device)
                            output_device = selected_device
                            output_revision = selected_revision
                            failed_output_revision = None
                            emit("output_changed", selected_device)
                        except Exception as error:
                            failed_output_revision = selected_revision
                            emit("output_switch_error", str(error))

                    await asyncio.to_thread(output.write, data)
                    queued_ms = max(0.0, queued_ms - duration_ms)
                    frames.task_done()
                    if finished and not pending and frames.empty():
                        break
                    if queued_ms <= 0:
                        primed = False

            reader = asyncio.create_task(read_frames())
            latency_monitor = asyncio.create_task(measure_network_rtt())
            try:
                await play_frames()
            finally:
                for task in (reader, latency_monitor):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(reader, latency_monitor, return_exceptions=True)
    except ConnectionClosed:
        pass
    except Exception as error:
        emit("error", str(error))
    finally:
        emit("disconnected", peer)
