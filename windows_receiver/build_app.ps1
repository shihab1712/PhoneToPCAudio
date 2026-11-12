$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$tempPath = Join-Path $projectRoot '.tmp'
$configPath = Join-Path $projectRoot '.pyinstaller'

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python environment not found: $python"
}
New-Item -ItemType Directory -Force -Path $tempPath | Out-Null
New-Item -ItemType Directory -Force -Path $configPath | Out-Null
$env:TEMP = $tempPath
$env:TMP = $tempPath
$env:PYINSTALLER_CONFIG_DIR = $configPath

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean --windowed `
        --name PhoneToPcReceiver --collect-all _sounddevice_data receiver_app.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

Write-Host "Windows app created at: $(Join-Path $projectRoot 'dist\PhoneToPcReceiver\PhoneToPcReceiver.exe')"
