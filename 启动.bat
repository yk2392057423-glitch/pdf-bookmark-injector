@echo off
title PDF Bookmark Injector

echo ================================================
echo   PDF Bookmark Injector - Starting...
echo ================================================
echo.

cd /d "%~dp0"

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] %PYVER%

:: Check Tesseract
if not defined TESSERACT_CMD (
    if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (
        set "TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
)

if defined TESSERACT_CMD (
    "%TESSERACT_CMD%" --version >nul 2>&1
    if errorlevel 1 goto tesseract_missing
    echo [OK] Tesseract found
    :: Derive tessdata dir from the exe directory (%%~dpT = drive+path with trailing backslash)
    for %%T in ("%TESSERACT_CMD%") do set "TESSDATA_PREFIX=%%~dpTtessdata"
    goto tesseract_ok
)

:tesseract_missing
echo.
echo [WARN] Tesseract OCR not found.
echo Download from: https://github.com/UB-Mannheim/tesseract/wiki
echo Remember to select the "chi_sim" language pack during install.
echo.
echo If installed in a non-default path, set TESSERACT_CMD before running:
echo   set TESSERACT_CMD=D:\your\path\tesseract.exe
echo.
echo Press any key to continue anyway...
pause >nul

:tesseract_ok

:: Install Python dependencies
echo.
echo [1/2] Installing Python dependencies...
pip install -r requirements.txt -q --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install dependencies. Check your network connection.
    pause
    exit /b 1
)
echo [OK] Dependencies ready

:: Start server
echo.
echo [2/2] Starting server...
echo.
echo   URL: http://localhost:5000
echo   Close this window to stop the server.
echo.
echo ================================================
echo.

start /b cmd /c "timeout /t 2 >nul && start http://localhost:5000"

cd webapp
python app.py

echo.
echo Server stopped. Press any key to exit...
pause >nul
