"""Shared WebSocket PCM receive and local playback logic."""

from array import array
import sys
from threading import Lock

import sounddevice as sd
from websockets.exceptions import ConnectionClosed

RATE = 48_000
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_BYTES = 3_840  # 20 ms at 48 kHz, stereo, signed 16-bit PCM


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


async def receive_audio(websocket, *, output_device=None, volume_control=None, on_event=None):
    """Receive PCM frames and play them to the selected Windows output."""
    def emit(name, value=None):
        if on_event is not None:
            on_event(name, value)

    if websocket.request.path != "/audio":
        await websocket.close(1008, "Use /audio")
        return

    peer = websocket.remote_address
    emit("connected", peer)
    try:
        with sd.RawOutputStream(
            samplerate=RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=0,
            device=output_device,
        ) as output:
            async for message in websocket:
                if not isinstance(message, bytes):
                    emit("warning", "Ignored a non-binary message")
                    continue
                if len(message) % (CHANNELS * SAMPLE_WIDTH):
                    emit("warning", f"Ignored malformed PCM packet ({len(message)} bytes)")
                    continue
                if volume_control is not None:
                    message = _scale_pcm16le(message, volume_control.get_gain())
                output.write(message)
                emit("bytes", len(message))
    except ConnectionClosed:
        pass
    except Exception as error:
        emit("error", str(error))
    finally:
        emit("disconnected", peer)
