@echo off
title Cell Coach
cd /d "%~dp0"
where python >nul 2>nul || (echo [ERROR] Python not found. Install from python.org, tick "Add to PATH". & pause & exit /b 1)

rem ── Telephony tunnel: reserved ngrok domain -> this app's port 5099 ──
rem Kill any stale ngrok first so we never end up with two tunnels fighting.
taskkill /IM ngrok.exe /F >nul 2>nul
echo Starting ngrok tunnel: https://atrophy-strict-heroics.ngrok-free.dev -^> http://localhost:5099
start "Cell Coach Tunnel" /min "C:\Users\Admin\data_center\tools\ngrok.exe" http --domain=atrophy-strict-heroics.ngrok-free.dev 5099

echo Starting Cell Coach... your browser will open. Keep this window open while you work.
echo (Closing this window stops BOTH the app and the phone tunnel.)
python cellcoach.py

rem ── Server exited: take the tunnel down with it so no orphan is left ──
taskkill /IM ngrok.exe /F >nul 2>nul
pause
