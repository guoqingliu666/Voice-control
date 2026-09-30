$ErrorActionPreference = 'Stop'
$PackageRoot = Split-Path -Parent $PSScriptRoot
$RuntimeRoot = 'D:\VoiceBridgeRuntime'
$ModelRoot = 'D:\VoiceBridgeModels'
$CacheRoot = 'D:\VoiceBridgeCache'
$TempRoot = 'D:\ChatGPT\Temp'

function Stop-WithMessage([string]$Message) {
    Write-Host "`n[失败] $Message" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $RuntimeRoot, $ModelRoot, $CacheRoot, $TempRoot | Out-Null
$env:TEMP = $TempRoot
$env:TMP = $TempRoot
$env:UV_CACHE_DIR = $CacheRoot
$env:HF_HOME = $ModelRoot
$env:MODELSCOPE_CACHE = $ModelRoot
$env:HF_HUB_DISABLE_XET = '1'

$SourceRoot = Join-Path $PackageRoot 'upstream_pyvideotrans'
if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot 'pyproject.toml'))) {
    Stop-WithMessage '安装包不完整：找不到 upstream_pyvideotrans\pyproject.toml。请重新下载并完整解压 ZIP。'
}

Write-Host '[1/4] 正在复制程序文件到 D:\VoiceBridgeRuntime ...' -ForegroundColor Cyan
Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Force | ForEach-Object {
    $Relative = $_.FullName.Substring($SourceRoot.Length).TrimStart('\')
    $Target = Join-Path $RuntimeRoot $Relative
    New-Item -ItemType Directory -Force -Path (Split-Path $Target) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $Target -Force
}

$ModelsLink = Join-Path $RuntimeRoot 'models'
if (-not (Test-Path -LiteralPath $ModelsLink)) {
    New-Item -ItemType Junction -Path $ModelsLink -Target $ModelRoot | Out-Null
    Write-Host "已将模型目录指向 $ModelRoot" -ForegroundColor Green
}

$UvExe = Join-Path $PackageRoot 'tools\uv.exe'
if (-not (Test-Path -LiteralPath $UvExe)) {
    $UvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($UvCommand) { $UvExe = $UvCommand.Source }
    else { Stop-WithMessage '找不到 uv.exe。请重新下载完整安装包，或先从 https://docs.astral.sh/uv/ 安装 uv。' }
}

Write-Host '[2/4] 正在创建 Python 3.10 环境并安装依赖（首次可能需要较长时间和数 GB 磁盘空间）...' -ForegroundColor Cyan
Push-Location $RuntimeRoot
try {
    & $UvExe sync --frozen
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage '依赖安装失败。请检查网络、磁盘空间和 NVIDIA 驱动后重新运行本安装程序。' }
} finally {
    Pop-Location
}

$PythonExe = Join-Path $RuntimeRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonExe)) { Stop-WithMessage "环境创建后仍找不到 $PythonExe。" }

Write-Host '[3/4] 检查 FFmpeg 和 SoX ...' -ForegroundColor Cyan
foreach ($Name in @('ffmpeg', 'ffprobe', 'sox')) {
    if (Get-Command $Name -ErrorAction SilentlyContinue) {
        Write-Host "[通过] $Name" -ForegroundColor Green
    } else {
        Write-Host "[提示] 未检测到 $Name。可在管理员 PowerShell 执行：winget install --id ChrisBagwell.SoX --exact；FFmpeg 请安装后加入 PATH。" -ForegroundColor Yellow
    }
}

Write-Host '[4/4] 验证本地 Python 模块 ...' -ForegroundColor Cyan
& $PythonExe -c 'import PySide6, torch, videotrans; print("PySide6/torch/videotrans OK")'
if ($LASTEXITCODE -ne 0) { Stop-WithMessage 'Python 模块验证失败，请把本窗口中的完整错误信息保存后反馈。' }

Write-Host "`n安装完成。下一步双击“运行自检.bat”，通过后再双击“启动桌面版.bat”。" -ForegroundColor Green
Read-Host '按回车键关闭'
