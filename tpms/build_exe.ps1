# TPMS 打包脚本 (PowerShell) - 智能自适应标准 .venv 与 Conda
$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# 1. 自动探测 Python 解释器
$PythonExe = "python"
if (Test-Path ".\.venv\Scripts\python.exe") {
    $PythonExe = ".\.venv\Scripts\python.exe"
    Write-Host "[*] 检测到本地虚拟环境: .venv" -ForegroundColor Cyan
} elseif (Test-Path ".\venv\Scripts\python.exe") {
    $PythonExe = ".\venv\Scripts\python.exe"
    Write-Host "[*] 检测到本地虚拟环境: venv" -ForegroundColor Cyan
} elseif (Test-Path "D:\project_momo\project_venv\venv_crashsensor\python.exe") {
    $PythonExe = "D:\project_momo\project_venv\venv_crashsensor\python.exe"
    Write-Host "[*] 检测到 Conda 虚拟环境: venv_crashsensor" -ForegroundColor Cyan
} else {
    Write-Host "[*] 使用系统默认 Python" -ForegroundColor Cyan
}

# 2. 如果存在 Conda 特有的 Library\bin 则自动加入 PATH
try {
    $PyPath = (Resolve-Path $PythonExe).Path
    $PyDir = Split-Path -Parent $PyPath
    $CondaLibBin = Join-Path $PyDir "Library\bin"
    if (-not (Test-Path $CondaLibBin)) {
        $CondaLibBin = Join-Path (Split-Path -Parent $PyDir) "Library\bin"
    }
    if (Test-Path $CondaLibBin) {
        Write-Host "[*] 检测到 Conda Library 路径，注入 DLL 搜索目录: $CondaLibBin" -ForegroundColor Gray
        $env:PATH = "$CondaLibBin;$env:PATH"
    }
} catch {
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  TPMS 车型打标与全基地汇总系统 - 一键打包 EXE" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

Write-Host "[*] 正在执行 PyInstaller 单文件打包 (读取 TPMS.spec)..." -ForegroundColor Yellow

& $PythonExe -m PyInstaller --noconfirm TPMS.spec

if ($LASTEXITCODE -eq 0) {
    Write-Host "[*] 正在同步 data/ 规范与地区模板文件到 dist\data\..." -ForegroundColor Cyan
    if (-not (Test-Path "dist\data")) { New-Item -ItemType Directory -Path "dist\data" | Out-Null }
    Copy-Item "data\*.xlsx" -Destination "dist\data\" -Force -ErrorAction SilentlyContinue

    # 自动清理 build 编译缓存目录，保持项目轻量 (约节省 50MB+)
    if (Test-Path "build") {
        Write-Host "[*] 正在自动清理 build 临时缓存目录..." -ForegroundColor Gray
        Remove-Item -Recurse -Force "build" -ErrorAction SilentlyContinue
    }

    Write-Host ""
    Write-Host "[OK] 打包成功！" -ForegroundColor Green
    Write-Host "可执行文件: dist\TPMS.exe" -ForegroundColor Green
    Write-Host "配置文件夹: dist\data\ (已包含 车型分类规范.xlsx 与 地区列表.xlsx)" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[Error] 打包失败，退出码: $LASTEXITCODE" -ForegroundColor Red
}
