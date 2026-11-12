"""Receive raw signed 16-bit little-endian stereo PCM and play it locally."""
import argparse
import asyncio
import logging

from websockets.asyncio.server import serve
from audio_receiver import FRAME_BYTES, RATE, receive_audio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("phone_to_pc")

def log_event(name, value):
    if name == "connected":
        log.info("Audio client connected: %s", value)
    elif name == "disconnected":
        log.info("Audio client disconnected: %s", value)
    elif name == "error":
        log.error("Audio playback failed: %s", value)
    elif name == "warning":
        log.warning("%s", value)

async def main(host: str, port: int):
    log.info("Listening on ws://%s:%d/audio (PCM %d Hz, stereo, s16le)", host, port, RATE)
    async with serve(
        lambda websocket: receive_audio(websocket, on_event=log_event),
        host,
        port,
        max_size=FRAME_BYTES * 8,
        ping_interval=20,
        ping_timeout=20,
    ):
        await asyncio.Future()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Listen address (default: all network adapters)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        pass
