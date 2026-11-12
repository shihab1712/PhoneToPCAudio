# Setup and run

## Windows receiver

The receiver has a desktop app and a command-line version. On Windows 10 or newer, install Python 3.11 or newer if you want to build or run it from source. From the project root in PowerShell:

```powershell
cd windows_receiver
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-app.txt
.\build_app.ps1
```

The portable app is generated under `windows_receiver\dist\PhoneToPcReceiver\`. The build script removes its temporary build/cache files after a successful package and keeps the runnable app folder. Keep the entire folder together when copying it to another PC. Open `PhoneToPcReceiver.exe`, choose the PC audio output, adjust **Receiver volume**, and press **Start receiver**. This slider controls only the phone stream, not Windows system volume. If Windows Firewall asks, allow access on the **Private network** used by the phone. Do not expose port `8765` to public networks.

To create a standard Windows installer, install Inno Setup 6, build the portable app, then run `windows_receiver\build_installer.ps1`. The setup program is written to `windows_receiver\dist\installer\PhoneToPcAudio-Setup-1.0.0.exe`. It installs per-user, creates a Start menu shortcut and offers an optional desktop shortcut. It does not add firewall rules; allow the app on the Private network if Windows asks.

To run the desktop app directly from Python instead of packaging it, run `python receiver_app.py`. To use the command-line receiver, run `python receiver.py`; it plays through the system-default output. Both versions use the same PCM/WebSocket receive code.

## Android app

Install Flutter stable and Android Studio using their official distribution channels. In Android Studio’s SDK Manager, install Android SDK Platform 34, Android SDK Build Tools 34.0.0, NDK 28.2.13676358, and Android SDK Platform-Tools, then accept the Android SDK licenses. Android playback capture requires Android 10 (API 29) or newer.

From the project root in PowerShell:

```powershell
cd android_app
flutter pub get
flutter doctor
flutter analyze
flutter build apk --debug
```

The APK is written to `android_app\build\app\outputs\flutter-apk\app-debug.apk`. Connect an Android 10+ phone with USB debugging enabled or use an emulator. `flutter run` installs and opens the app on a connected device.

## Connect over Wi-Fi

Run the Windows receiver and connect both devices to the same trusted private Wi-Fi network. Enter one of the PC addresses shown in the receiver app and port `8765` in the phone app. If Windows Firewall blocks the connection, allow the receiver on the Private network in Windows Security.

## Connect over USB

Enable USB debugging and authorize the PC on the phone. With the receiver running, execute:

```powershell
adb devices
adb reverse tcp:8765 tcp:8765
```

Use `127.0.0.1` and port `8765` in the phone app. Remove the mapping with `adb reverse --remove tcp:8765`.

## Audio and limitations

Audio is raw PCM at 48 kHz, stereo, signed 16-bit little-endian. Android requests per-session playback-capture approval. Apps can opt out, and protected audio may be silent. Keep the phone app open during streaming; background operation is not supported in this initial version.

The WebSocket has no authentication or encryption. Use it only on a trusted private network or through USB ADB reverse. Do not forward port `8765` to the public internet.
