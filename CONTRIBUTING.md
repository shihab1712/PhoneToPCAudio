# Contributing

Thanks for helping improve PhoneToPC. Bug reports, documentation fixes, and code contributions are welcome.

## Before opening a change

- Check existing issues and discussions for related work.
- Keep changes focused and describe what problem they solve.
- Do not include generated build output, signing keys, private addresses, or audio recordings.
- For audio changes, include the sample rate, channel count, and sample format in the description.

## Development checks

### Android app

From `android_app/`:

```powershell
flutter pub get
flutter analyze
flutter build apk --debug
```

### Windows receiver

From `windows_receiver/`, create and activate a Python virtual environment, then install the app requirements:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-app.txt
python -m py_compile audio_receiver.py receiver.py receiver_app.py
python receiver_app.py
```

Build the portable Windows package with `.\build_app.ps1` in PowerShell. To create the Windows installer, install Inno Setup 6 and run `..\build_installer.ps1` from the receiver directory.

## Pull requests

Include a concise summary, steps to reproduce or review, and any relevant platform or device details. Mention tests or manual checks performed. Do not attach captured audio unless it is specifically needed and the people in it have agreed to its use.
