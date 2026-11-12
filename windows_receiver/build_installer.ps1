$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$portableAppFolder = 'dist\PhoneToPcReceiver'
$volumeAppFolder = 'dist\PhoneToPcReceiver-volume'
if (Test-Path -LiteralPath (Join-Path $projectRoot "$volumeAppFolder\PhoneToPcReceiver.exe")) {
    $portableAppFolder = $volumeAppFolder
}
$portableApp = Join-Path $projectRoot "$portableAppFolder\PhoneToPcReceiver.exe"
$installerScript = Join-Path $projectRoot 'PhoneToPcAudio.iss'
$outputInstaller = Join-Path $projectRoot 'dist\installer\PhoneToPcAudio-Setup-1.0.0.exe'

if (-not (Test-Path -LiteralPath $portableApp)) {
    throw "Portable app not found. Run .\build_app.ps1 first: $portableApp"
}
if (-not (Test-Path -LiteralPath $installerScript)) {
    throw "Inno Setup definition not found: $installerScript"
}

$compiler = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if (-not $compiler) {
    $programFilesX86 = [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $programFilesX86 'Inno Setup 6\ISCC.exe')
    )
    $compiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $compiler) {
    throw 'Inno Setup 6 is required. Install it from https://jrsoftware.org/isdl.php, then rerun this script.'
}

Push-Location $projectRoot
try {
    & $compiler '/Qp' "/DAppFilesDir=$portableAppFolder" $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $outputInstaller)) {
    throw "Installer compiler completed, but output was not found: $outputInstaller"
}
Get-Item -LiteralPath $outputInstaller | Select-Object FullName, Length, LastWriteTime
