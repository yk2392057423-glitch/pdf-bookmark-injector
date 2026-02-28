@echo off
chcp 65001 >nul
title PDF 书签注入工具

echo ================================================
echo   PDF 书签注入工具 - 启动中...
echo ================================================
echo.

:: 切换到脚本所在目录，无论从哪里双击都能正常运行
cd /d "%~dp0"

:: ── 检查 Python ──────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 或以上版本。
    echo.
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] %PYVER%

:: ── 检查 Tesseract ───────────────────────────────
if defined TESSERACT_CMD (
    "%TESSERACT_CMD%" --version >nul 2>&1
    if errorlevel 1 goto tesseract_missing
    echo [OK] Tesseract ^(来自环境变量^)
    goto tesseract_ok
)
"C:\Program Files\Tesseract-OCR\tesseract.exe" --version >nul 2>&1
if errorlevel 1 goto tesseract_missing
echo [OK] Tesseract OCR
goto tesseract_ok

:tesseract_missing
echo.
echo [警告] 未检测到 Tesseract OCR。
echo 请从以下地址下载并安装（选 chi_sim 语言包）：
echo https://github.com/UB-Mannheim/tesseract/wiki
echo.
echo 如已安装在非默认路径，请设置环境变量后重新运行：
echo   TESSERACT_CMD=你的安装路径\tesseract.exe
echo.
echo 按任意键继续（目录页自动检测功能可能异常）...
pause >nul

:tesseract_ok

:: ── 安装 Python 依赖 ─────────────────────────────
echo.
echo [1/2] 检查并安装 Python 依赖...
pip install -r requirements.txt -q --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请检查网络连接后重试。
    pause
    exit /b 1
)
echo [OK] 依赖已就绪

:: ── 启动服务 ─────────────────────────────────────
echo.
echo [2/2] 启动服务...
echo.
echo  访问地址: http://localhost:5000
echo  关闭此窗口即可停止服务
echo.
echo ================================================
echo.

:: 2 秒后自动打开浏览器
start /b cmd /c "timeout /t 2 >nul && start http://localhost:5000"

cd webapp
python app.py

echo.
echo 服务已停止。按任意键关闭...
pause >nul
