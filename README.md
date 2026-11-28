# PhoneToPC

Stream eligible Android audio to a Windows PC over Wi-Fi or USB. Choose **Audio only** or **Audio + video** in the Android app; video mode shows the phone screen in its own **Video stream** dashboard section. The Android app requires Android 10 or newer. Audio capture depends on the source app allowing playback capture.

## Download

Download the files from the [latest GitHub release](https://github.com/shihab1712/PhoneToPC/releases/latest). Under **Assets**, choose:

- **Windows installer** (`PhoneToPC-Setup-1.1.1.exe`) — installs the receiver for the current Windows user.
- **Android app** (`PhoneToPC-1.1.1.apk`) — install this on your phone. This APK is for direct installation, not the Google Play Store.

## Install

### Windows receiver

1. Download and open the Windows installer.
2. Follow the setup steps. You can choose whether to add a desktop shortcut.
3. Open **PhoneToPC** from the Start menu.
4. Select **Check for updates** in the app header to check GitHub and open the release page when a newer version is available.

The installer does not change Windows Firewall settings. If Windows asks, allow the receiver on your **Private network**.

### Android app

1. Download the APK on your Android phone.
2. Open the downloaded file. If Android asks, allow your browser or file manager to install apps, then continue the installation.
3. Open **PhoneToPC**.

The first time you start a stream, Android asks you to approve capture. Approve it to send audio; if you select **Audio + video**, approve screen sharing too.

## Connect over Wi-Fi

1. Connect the PC and phone to the same trusted, private Wi-Fi network. Guest networks may block devices from seeing each other.
2. In the Windows receiver, find the PC address under **Wi-Fi stream**, then select **Start Wi-Fi receiver**.
3. On the phone, open the **Stream** page and select **Wi-Fi**.
4. Enter the PC address shown in the receiver. Leave the port at `8765` unless you changed it in the receiver.
5. Choose **Audio only** or **Audio + video**, tap **Start streaming**, and approve Android’s capture prompt. In video mode, Android asks for screen-sharing approval and the Windows receiver displays the screen in its **Video stream** section.

Play audio in an app that allows capture. The phone’s **Stream status** shows whether it is connected and how much audio it has sent.

## Connect over USB

1. On the phone, enable **USB debugging** in Developer options.
2. Connect the phone to the PC with a USB cable. Unlock the phone and approve the **Allow USB debugging** prompt.
3. In the Windows receiver, select **Start USB receiver**. It sets up USB forwarding automatically.
4. On the phone’s **Stream** page, select **USB**. The PC address should be `127.0.0.1`; leave the port at `8765` unless you changed it in the receiver.
5. Choose **Audio only** or **Audio + video**, tap **Start streaming**, and approve Android’s capture prompt. In video mode, Android asks for screen-sharing approval and the Windows receiver displays the screen in its **Video stream** section.

The USB connection requires Android SDK **Platform-Tools** (`adb`). Install them using Android Studio’s SDK Manager if the receiver reports that `adb` is missing.

## Everyday controls

- **Audio output:** Choose the PC speakers or headphones in **Receiver settings**. You can change the output while the phone is connected.
- **Receiver volume:** Changes the phone stream volume without changing Windows system volume.
- **Phone media mute:** In the Windows receiver settings, select **Mute phone media while connected**. It can be selected before the phone connects; the phone’s previous media volume is restored when you uncheck it, stop streaming, or disconnect. This changes the shared Android media volume used by media apps.
- **Audio buffer:** Wi-Fi and USB have separate sliders. More buffer can reduce dropouts but adds delay. Wi-Fi starts at 100 ms; USB starts at 0 ms. The status panel shows network RTT and an estimated audio delay.
- **Global volume shortcuts:** The defaults are `Ctrl+Alt+Up`, `Ctrl+Alt+Down`, and `Ctrl+Alt+M`. Use **Change** to customize them. They work while the receiver is minimized and change receiver volume in 5% steps.
- **Dashboard layout:** Select **Edit dashboard** to drag sections into a new order. Use **×** to hide a section and **Add section** to bring it back. Select **Done editing** to finish.
- **Theme:** In the Android app, open **Settings** from the bottom bar and choose **System**, **Light**, or **Dark**.
- **Screen preview:** In **Audio + video** mode, Android sends resized screen images to the separate **Video stream** dashboard section. Select **Fullscreen (F)** or press **F** while the receiver is focused; press **F** or **Esc** to exit. The receiver skips older frames if it needs to catch up.
- **Screen quality and frame rate:** Choose **Low**, **Balanced**, or **High** quality and **30 FPS** or **60 FPS** before starting. Higher settings use more phone processing and network bandwidth; the achieved frame rate depends on the phone, Wi-Fi/USB connection, and PC.
- **Mouse control:** On Android, select **Enable mouse control on phone** and enable **PhoneToPC mouse control** under Accessibility. On Windows, turn on **Allow mouse control** in the Video stream section, then click or drag on the preview. The Android service can send gestures but does not read screen contents. When the phone display is off, the Windows receiver sends mouse input over the authorized USB debugging connection so control can continue while mirroring.
- **Phone display:** On Android 15 or newer, the Windows Video stream section can turn the display off while mirroring. This requires one authorized phone connected over USB with USB debugging. The receiver turns the display back on when the stream ends.
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

The stream sends audio and, if selected, screen images over WebSocket without authentication or encryption. Use Wi-Fi only on a trusted private network, or connect over USB. Do not expose or forward port `8765` to the public internet.

## License

MIT. See [LICENSE](LICENSE).
