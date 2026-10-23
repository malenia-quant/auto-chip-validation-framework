@echo off
chcp 65001 >nul
echo ========================================================
echo   TPMS 车型打标与全基地汇总系统 - 一键打包 EXE 工具
echo ========================================================

cd /d "%~dp0"

rem 1. 自动探测 Python 解释器
set "PYTHON_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
    echo [*] 检测到本地虚拟环境: .venv
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_EXE=venv\Scripts\python.exe"
    echo [*] 检测到本地虚拟环境: venv
) else if exist "D:\project_momo\project_venv\venv_crashsensor\python.exe" (
    set "PYTHON_EXE=D:\project_momo\project_venv\venv_crashsensor\python.exe"
    echo [*] 检测到开发机 Conda 环境: venv_crashsensor
) else (
    set "PYTHON_EXE=python"
    echo [*] 使用系统默认 Python
)

rem 2. 如果存在 Conda Library\bin，则注入 PATH
if exist "D:\project_momo\project_venv\venv_crashsensor\Library\bin" (
    set "PATH=D:\project_momo\project_venv\venv_crashsensor\Library\bin;%PATH%"
)

rem 3. 检查并安装打包工具 PyInstaller
echo [*] 正在检查打包工具 pyinstaller...
"%PYTHON_EXE%" -m pip install pyinstaller --upgrade --quiet

rem 4. 使用 TPMS.spec 执行打包（已内置打包 Conda Library\bin 下的 ffi.dll / _ctypes 等依赖）
echo [*] 开始执行打包 (读取 TPMS.spec 配置)...
"%PYTHON_EXE%" -m PyInstaller --noconfirm TPMS.spec

if %ERRORLEVEL% equ 0 (
    echo [*] 正在将 data/ 规范与地区模板同步至 dist/data/ 目录...
    if not exist "dist\data" mkdir "dist\data"
    copy /y "data\车型分类规范.xlsx" "dist\data\" >nul 2>&1
    copy /y "data\地区列表.xlsx" "dist\data\" >nul 2>&1
    copy /y "data\国家列表.xlsx" "dist\data\" >nul 2>&1
    rem 自动清理 build 编译临时缓存目录
    if exist "build" (
        echo [*] 正在自动清理 build 临时缓存目录...
        rd /s /q "build" >nul 2>&1
    )
    echo.
    echo ========================================================
    echo [OK] 打包成功！
    echo 可执行文件路径: dist\TPMS.exe
    echo 规范数据文件夹: dist\data\ (已包含 车型分类规范.xlsx 与 地区列表.xlsx)
    echo ========================================================
) else (
    echo.
    echo [Error] 打包失败，请检查控制台错误信息。
)

pause
