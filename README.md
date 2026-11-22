# Phone-to-PC Audio

Stream eligible Android audio to a Windows PC over Wi-Fi or USB. The Android app requires Android 10 or newer. Audio capture depends on the source app allowing playback capture.

## Download

Download the files from the [latest GitHub release](https://github.com/shihab1712/PhoneToPCAudio/releases/latest). Under **Assets**, choose:

- **Windows installer** (`PhoneToPcAudio-Setup-1.0.0.exe`) — installs the receiver for the current Windows user.
- **Android app** (`PhoneToPcAudio-1.0.0.apk`) — install this on your phone. This APK is for direct installation, not the Google Play Store.

## Install

### Windows receiver

1. Download and open the Windows installer.
2. Follow the setup steps. You can choose whether to add a desktop shortcut.
3. Open **Phone-to-PC Audio** from the Start menu.

The installer does not change Windows Firewall settings. If Windows asks, allow the receiver on your **Private network**.

### Android app

1. Download the APK on your Android phone.
2. Open the downloaded file. If Android asks, allow your browser or file manager to install apps, then continue the installation.
3. Open **Phone to PC Audio**.

The first time you start a stream, Android asks you to approve playback capture. Approve it to send audio to the PC.

## Connect over Wi-Fi

1. Connect the PC and phone to the same trusted, private Wi-Fi network. Guest networks may block devices from seeing each other.
2. In the Windows receiver, find the PC address under **Wi-Fi stream**, then select **Start Wi-Fi receiver**.
3. On the phone, open the **Stream** page and select **Wi-Fi**.
4. Enter the PC address shown in the receiver. Leave the port at `8765` unless you changed it in the receiver.
5. Tap **Start streaming** and approve Android’s playback-capture prompt if it appears.

Play audio in an app that allows capture. The phone’s **Stream status** shows whether it is connected and how much audio it has sent.

## Connect over USB

1. On the phone, enable **USB debugging** in Developer options.
2. Connect the phone to the PC with a USB cable. Unlock the phone and approve the **Allow USB debugging** prompt.
3. In the Windows receiver, select **Start USB receiver**. It sets up USB forwarding automatically.
4. On the phone’s **Stream** page, select **USB**. The PC address should be `127.0.0.1`; leave the port at `8765` unless you changed it in the receiver.
5. Tap **Start streaming** and approve Android’s playback-capture prompt if requested.

The USB connection requires Android SDK **Platform-Tools** (`adb`). Install them using Android Studio’s SDK Manager if the receiver reports that `adb` is missing.

## Everyday controls

- **Audio output:** Choose the PC speakers or headphones in **Receiver settings**. You can change the output while the phone is connected.
- **Receiver volume:** Changes the phone stream volume without changing Windows system volume.
- **Audio buffer:** Wi-Fi and USB have separate sliders. More buffer can reduce dropouts but adds delay. Wi-Fi starts at 100 ms; USB starts at 0 ms. The status panel shows network RTT and an estimated audio delay.
- **Global volume shortcuts:** The defaults are `Ctrl+Alt+Up`, `Ctrl+Alt+Down`, and `Ctrl+Alt+M`. Use **Change** to customize them. They work while the receiver is minimized and change receiver volume in 5% steps.
- **Dashboard layout:** Select **Edit dashboard** to drag sections into a new order. Use **×** to hide a section and **Add section** to bring it back. Select **Done editing** to finish.
- **Theme:** In the Android app, open **Settings** from the bottom bar and choose **System**, **Light**, or **Dark**.
- **Stop:** Select **Stop streaming** on the phone and stop the active receiver from its Wi-Fi or USB section when you are finished.

## Troubleshooting

**The phone cannot connect over Wi-Fi**

- Make sure both devices are on the same private Wi-Fi network.
- Check that the address in the phone app matches one of the PC addresses shown by the receiver, and that both use the same port.
- If Windows Firewall asks, allow the receiver on the network’s **Private** profile.
- Some routers enable client or AP isolation, which prevents devices on Wi-Fi from communicating.

**USB does not connect**

- Unlock the phone and accept the USB debugging authorization prompt.
- Use a data-capable USB cable and try another USB port.
- Make sure Android SDK Platform-Tools are installed. Stop and start the USB receiver again after reconnecting the phone.

**The receiver connects but there is no sound**

- Check the receiver’s selected audio output and **Receiver volume**.
- Start audio in the phone app you want to capture. Some apps block playback capture, and protected audio may be silent.
- Keep the phone app open while streaming. Background streaming is not supported in this version.

## Build from source

See [docs/SETUP.md](docs/SETUP.md) for Windows and Android development, build, and troubleshooting instructions.

## Privacy and network security

The stream uses raw PCM audio over WebSocket without authentication or encryption. Use Wi-Fi only on a trusted private network, or connect over USB. Do not expose or forward port `8765` to the public internet.

## License

MIT. See [LICENSE](LICENSE).
