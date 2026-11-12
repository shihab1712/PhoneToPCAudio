# Architecture

## Phone

The Flutter UI collects the PC address and port, opens a WebSocket at `/audio`, and asks the native Android side to begin capture. `MainActivity.kt` requests microphone permission and Android's MediaProjection playback-capture approval. `CaptureService.kt` uses `AudioPlaybackCaptureConfiguration` and `AudioRecord` to capture eligible media/game playback and emits PCM frames to Flutter.

## Connection

The phone sends binary WebSocket messages over TCP port `8765`. Wi-Fi uses the PC's private IPv4 address. USB uses Android Debug Bridge's reverse port mapping, so the phone connects to `127.0.0.1`.

## Windows

`receiver_app.py` provides the desktop interface. It runs the WebSocket server on a background asyncio loop so the window remains responsive. `receiver.py` provides a command-line entry point. Both use `audio_receiver.py` to validate and play frames through `sounddevice`.

## Audio format

- 48,000 samples per second
- 2 channels
- Signed 16-bit little-endian PCM
- Binary WebSocket frames, typically 20 ms each

## Trust boundary

The local WebSocket does not authenticate clients or encrypt audio. The receiver listens on all network interfaces so a phone on the LAN can reach it. Keep the connection on a trusted private network or USB reverse and do not expose the port to the internet.
