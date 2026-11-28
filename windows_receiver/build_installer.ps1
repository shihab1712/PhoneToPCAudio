$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$portableAppFolder = 'dist\PhoneToPC'
$portableApp = Join-Path $projectRoot "$portableAppFolder\PhoneToPC.exe"
$installerScript = Join-Path $projectRoot 'PhoneToPcAudio.iss'
$outputInstaller = Join-Path $projectRoot 'dist\installer\PhoneToPC-Setup-1.1.1.exe'
$tempPath = Join-Path $projectRoot '.tmp-installer'

if (-not (Test-Path -LiteralPath $portableApp)) {
    throw "Portable app not found. Run .\build_app.ps1 first: $portableApp"
}
if (-not (Test-Path -LiteralPath $installerScript)) {
    throw "Inno Setup definition not found: $installerScript"
}

$compiler = $env:INNO_SETUP_COMPILER
if ($compiler -and -not (Test-Path -LiteralPath $compiler)) {
    throw "Inno Setup compiler not found at INNO_SETUP_COMPILER: $compiler"
}
if (-not $compiler) {
    $compiler = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
}
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
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
New-Item -ItemType Directory -Force -Path $tempPath | Out-Null
$env:TEMP = $tempPath
$env:TMP = $tempPath
try {
    & $compiler '/Qp' '/DAppVersion=1.1.1' "/DAppFilesDir=$portableAppFolder" $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
    if (Test-Path -LiteralPath $tempPath) {
        $resolvedTemp = (Resolve-Path -LiteralPath $tempPath).Path.TrimEnd('\')
        $projectPrefix = $projectRoot.TrimEnd('\') + '\'
        if ($resolvedTemp.StartsWith($projectPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
        }
    }
}

if (-not (Test-Path -LiteralPath $outputInstaller)) {
    throw "Installer compiler completed, but output was not found: $outputInstaller"
}
Get-Item -LiteralPath $outputInstaller | Select-Object FullName, Length, LastWriteTime
