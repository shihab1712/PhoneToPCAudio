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
$buildSucceeded = $false
try {
    & $python -m PyInstaller --noconfirm --clean --windowed `
        --name PhoneToPcReceiver --collect-all _sounddevice_data receiver_app.py
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller exited with code $LASTEXITCODE"
    }
    $buildSucceeded = $true
} finally {
    Pop-Location
    if ($buildSucceeded) {
        $root = (Resolve-Path -LiteralPath $projectRoot).Path.TrimEnd('\')
        $rootPrefix = $root + '\'
        $generatedPaths = @(
            'build',
            '.pyinstaller',
            '.tmp',
            '__pycache__',
            'dist\PhoneToPcReceiver.exe'
        )
        foreach ($relativePath in $generatedPaths) {
            $candidate = Join-Path $root $relativePath
            if (Test-Path -LiteralPath $candidate) {
                $resolved = (Resolve-Path -LiteralPath $candidate).Path.TrimEnd('\')
                if (-not $resolved.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Refusing to remove a path outside the receiver project: $resolved"
                }
                Remove-Item -LiteralPath $resolved -Recurse -Force
            }
        }
    }
}

Write-Host "Windows app created at: $(Join-Path $projectRoot 'dist\PhoneToPcReceiver\PhoneToPcReceiver.exe')"
Write-Host 'Temporary build, cache, and scratch files were removed; the runnable app folder was kept.'
