@echo off
cd /d "%~dp0"
chcp 65001 >nul

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [信息] 未找到虚拟环境，正在创建 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo [信息] 开始打包，请先关闭正在运行的 FormatTool.exe ...
pyinstaller --noconfirm --clean --onefile --windowed --name "FormatTool" --collect-all customtkinter app.py
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo 打包完成：dist\FormatTool.exe
pause
