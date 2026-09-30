param(
    [ValidateSet('desktop', 'web')]
    [string]$Mode = 'desktop'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = if (Test-Path -LiteralPath 'D:\VoiceBridgeRuntime') {
    'D:\VoiceBridgeRuntime'
} else {
    Join-Path $ProjectRoot 'upstream_pyvideotrans'
}
$env:VOICEBRIDGE_RUNTIME_ROOT = $RuntimeRoot
$env:HF_HUB_DOWNLOAD_TIMEOUT = '120'
$env:HF_HUB_DISABLE_XET = '1'
$env:TEMP = 'D:\ChatGPT\Temp'
$env:TMP = 'D:\ChatGPT\Temp'
$env:HF_HOME = 'D:\VoiceBridgeModels'
$env:MODELSCOPE_CACHE = 'D:\VoiceBridgeModels'
$env:UV_CACHE_DIR = 'D:\VoiceBridgeCache'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
New-Item -ItemType Directory -Force -Path $env:HF_HOME, $env:MODELSCOPE_CACHE, $env:UV_CACHE_DIR | Out-Null

$BundledTools = Join-Path $ProjectRoot 'tools'
if (Test-Path -LiteralPath $BundledTools) { $env:PATH = "$BundledTools;$env:PATH" }

# Rubber Band provides substantially better time stretching than the FFmpeg
# fallback when translated speech has to be aligned to the original video.
$RubberBandDir = 'D:\VoiceBridgeTools\rubberband-4.0.0\rubberband-4.0.0-gpl-executable-windows'
if (Test-Path -LiteralPath (Join-Path $RubberBandDir 'rubberband.exe')) {
    $env:PATH = "$RubberBandDir;$env:PATH"
}

# winget may install SoX after Codex/Terminal has already inherited PATH. Discover it
# once so the current launcher works without requiring a Windows sign-out.
if (-not (Get-Command sox -ErrorAction SilentlyContinue)) {
    $SoxExe = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\ChrisBagwell.SoX_*\sox-*\sox.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($SoxExe) { $env:PATH = "$($SoxExe.DirectoryName);$env:PATH" }
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    throw 'FFmpeg was not found. Install FFmpeg and add it to PATH.'
}
if (-not (Get-Command sox -ErrorAction SilentlyContinue)) {
    throw 'SoX was not found. Run: winget install --id ChrisBagwell.SoX --exact'
}
if (-not (Get-Command rubberband -ErrorAction SilentlyContinue)) {
    Write-Warning 'Rubber Band was not found. Speech alignment will use the lower-quality FFmpeg fallback.'
}
if (-not (Test-Path -LiteralPath (Join-Path $RuntimeRoot 'pyproject.toml'))) {
    throw "Runtime is missing: $RuntimeRoot"
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
    # The conda `voice` interpreter is selected. Reuse the validated package
    # tree on D: through PYTHONPATH; no large CUDA wheels are copied to C:.
    $RuntimeSitePackages = Join-Path $RuntimeRoot '.venv\Lib\site-packages'
    $env:PYTHONPATH = if ($env:PYTHONPATH) {
        "$RuntimeSitePackages;$env:PYTHONPATH"
    } else {
        $RuntimeSitePackages
    }
} else {
    $PythonExe = $RuntimePython
}
$UvCommand = Get-Command uv -ErrorAction SilentlyContinue

# A complete local environment is already deployed. uv is needed only when the
# environment must be created or repaired, not for normal desktop/web startup.
if (-not (Test-Path -LiteralPath $PythonExe)) {
    if (-not $UvCommand) {
        throw "Python environment is missing: $PythonExe. Install uv to rebuild it."
    }
    Write-Host 'Creating the isolated environment...' -ForegroundColor Cyan
    & $UvCommand.Source sync --frozen
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    $PythonExe = $RuntimePython
}

Write-Host "Using Python: $PythonExe" -ForegroundColor Cyan
& $PythonExe -c 'import PySide6, torch, videotrans'
if ($LASTEXITCODE -ne 0) { throw 'The isolated Python environment is incomplete.' }

& $PythonExe (Join-Path $PSScriptRoot 'configure_defaults.py')
if ($LASTEXITCODE -ne 0) { throw 'Failed to write default configuration.' }

if ($Mode -eq 'web') {
    Write-Host 'Open http://127.0.0.1:7860 after the web UI starts.' -ForegroundColor Green
    & $PythonExe (Join-Path $RuntimeRoot 'webui.py') --host 127.0.0.1 --port 7860
} else {
    Write-Host 'Starting the desktop UI...' -ForegroundColor Green
    & $PythonExe (Join-Path $RuntimeRoot 'sp.py')
}

if ($LASTEXITCODE -ne 0) { throw "Application exited with code $LASTEXITCODE" }
