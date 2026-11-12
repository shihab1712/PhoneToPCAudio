# Phone-to-PC Audio

An open-source Android-to-Windows audio streamer. The Android app captures eligible playback on Android 10 or newer and sends raw PCM audio over WebSocket. The Windows receiver plays it through a selected output device and provides an independent volume slider for the phone stream.

## Components

- `android_app/` — Flutter interface and native Kotlin `AudioPlaybackCapture` service.
- `windows_receiver/` — Windows desktop receiver, shared PCM playback code, and command-line alternative.
- `docs/` — setup and architecture notes.

## Quick start

1. Build the Windows receiver by following [docs/SETUP.md](docs/SETUP.md). The portable app is generated under `windows_receiver/dist/` and is not committed to this source repository.
2. Open the receiver, choose an audio output, set the stream volume, and start listening.
3. Build and install the Android app, following the same setup guide.
4. Put the phone and PC on the same trusted Wi-Fi. In the phone app, enter the PC address shown by the receiver and port `8765`. For USB, configure `adb reverse` and use `127.0.0.1`.

The first capture session requires Android’s playback-capture approval. Some apps block capture, and the phone app must remain open while streaming.

## Audio and network security

The stream uses 48 kHz, stereo, signed 16-bit little-endian PCM. The WebSocket has no authentication or encryption. Use it only on a trusted private network or through USB ADB reverse; do not expose port `8765` to the public internet.

## License

MIT. See [LICENSE](LICENSE).
