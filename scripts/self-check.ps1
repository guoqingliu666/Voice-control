$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = if (Test-Path -LiteralPath 'D:\VoiceBridgeRuntime') {
    'D:\VoiceBridgeRuntime'
} else {
    Join-Path $ProjectRoot 'upstream_pyvideotrans'
}
$env:VOICEBRIDGE_RUNTIME_ROOT = $RuntimeRoot
$env:HF_HUB_DOWNLOAD_TIMEOUT = '120'
$env:TEMP = 'D:\ChatGPT\Temp'
$env:TMP = 'D:\ChatGPT\Temp'
$env:HF_HOME = 'D:\VoiceBridgeModels'
$env:MODELSCOPE_CACHE = 'D:\VoiceBridgeModels'
$env:UV_CACHE_DIR = 'D:\VoiceBridgeCache'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
New-Item -ItemType Directory -Force -Path $env:HF_HOME, $env:MODELSCOPE_CACHE, $env:UV_CACHE_DIR | Out-Null

$BundledTools = Join-Path $ProjectRoot 'tools'
if (Test-Path -LiteralPath $BundledTools) { $env:PATH = "$BundledTools;$env:PATH" }

$RubberBandDir = 'D:\VoiceBridgeTools\rubberband-4.0.0\rubberband-4.0.0-gpl-executable-windows'
if (Test-Path -LiteralPath (Join-Path $RubberBandDir 'rubberband.exe')) {
    $env:PATH = "$RubberBandDir;$env:PATH"
}

if (-not (Get-Command sox -ErrorAction SilentlyContinue)) {
    $SoxExe = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\ChrisBagwell.SoX_*\sox-*\sox.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($SoxExe) { $env:PATH = "$($SoxExe.DirectoryName);$env:PATH" }
}

Write-Host 'VoiceBridge environment check' -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
$ModelDir = Get-Item -LiteralPath (Join-Path $RuntimeRoot 'models') -ErrorAction SilentlyContinue
if ($ModelDir) { Write-Host "Models: $($ModelDir.FullName) -> $($ModelDir.Target)" }

foreach ($CommandName in @('ffmpeg', 'ffprobe', 'sox', 'rubberband', 'git')) {
    $Command = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($Command) {
        Write-Host "[PASS] $CommandName -> $($Command.Source)" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $CommandName was not found" -ForegroundColor Red
        exit 1
    }
}

$UvCommand = Get-Command uv -ErrorAction SilentlyContinue
if ($UvCommand) {
    Write-Host "[PASS] uv -> $($UvCommand.Source)" -ForegroundColor Green
} else {
    Write-Host '[INFO] uv was not found; the deployed .venv will be used directly.' -ForegroundColor Yellow
}

Set-Location -LiteralPath $RuntimeRoot
$RuntimePython = Join-Path $RuntimeRoot '.venv\Scripts\python.exe'
$CondaPythonCandidates = @(
    (Join-Path $env:USERPROFILE '.conda\envs\voice\python.exe'),
    'C:\ProgramData\anaconda3\envs\voice\python.exe',
    'D:\compute\anaconda\envs\voice\python.exe'
)
$PythonExe = $CondaPythonCandidates |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if ($PythonExe) {
    $RuntimeSitePackages = Join-Path $RuntimeRoot '.venv\Lib\site-packages'
    $env:PYTHONPATH = if ($env:PYTHONPATH) {
        "$RuntimeSitePackages;$env:PYTHONPATH"
    } else {
        $RuntimeSitePackages
    }
} else {
    $PythonExe = $RuntimePython
}
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Host "[FAIL] Python environment is missing: $PythonExe" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] python -> $PythonExe" -ForegroundColor Green
& $PythonExe (Join-Path $PSScriptRoot 'self_check.py')
exit $LASTEXITCODE
