@echo off
cd /d "%~dp0"
start "YuReader" /min py -3 app.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8775
