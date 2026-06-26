@echo off
echo Starting Berton Bottling App for mobile testing...
echo.
echo This will open two windows:
echo   1. The app server
echo   2. ngrok tunnel (shows the URL for your phone)
echo.
echo Use the https:// URL from ngrok on your phone.
echo.

start "Berton App Server" cmd /k "uv run uvicorn app.main:app --host 0.0.0.0 --port 8001"
timeout /t 3 /nobreak >nul
start "ngrok tunnel" cmd /k "ngrok http 8001"
