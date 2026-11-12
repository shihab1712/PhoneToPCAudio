"""Shared WebSocket PCM receive and local playback logic."""

import sounddevice as sd
from websockets.exceptions import ConnectionClosed

RATE = 48_000
CHANNELS = 2
SAMPLE_WIDTH = 2
FRAME_BYTES = 3_840  # 20 ms at 48 kHz, stereo, signed 16-bit PCM


async def receive_audio(websocket, *, output_device=None, on_event=None):
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
                output.write(message)
                emit("bytes", len(message))
    except ConnectionClosed:
        pass
    except Exception as error:
        emit("error", str(error))
    finally:
        emit("disconnected", peer)
