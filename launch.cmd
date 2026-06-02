@echo off
chcp 65001 >nul
title F5-TTS Hotkey Tool
cd /d "%~dp0"

echo ============================================
echo   F5-TTS Hotkey - Global TTS via Hotkey
echo ============================================
echo.

echo [1/2] Starting F5-TTS server...
start "F5-TTS-Server" /min cmd /c "call D:\Anaconda\condabin\conda.bat activate depthonnx && cd /d E:\GithubTools\F5-TTS && set HF_HOME=%USERPROFILE%\.cache\huggingface && set NO_PROXY=127.0.0.1,localhost,::1 && set no_proxy=127.0.0.1,localhost,::1 && f5-tts_infer-gradio"

echo [2/2] Waiting for server (may take 1-2 min)...
set /a COUNT=0
:WAIT_LOOP
timeout /t 5 /nobreak >nul
set /a COUNT+=1
if %COUNT% GTR 24 (
    echo ERROR: Server failed to start.
    pause
    exit /b 1
)
curl -s http://127.0.0.1:7860/config >nul 2>&1
if errorlevel 1 goto WAIT_LOOP

echo.
echo Server ready!
echo.
echo   Alt+X = Speak selected text
echo   Alt+Q = Quit
echo.

call D:\Anaconda\condabin\conda.bat activate depthonnx
python f5_tts_hotkey.py

echo Shutting down...
taskkill /FI "WINDOWTITLE eq F5-TTS-Server*" /F >nul 2>&1
