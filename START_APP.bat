@echo off
title Gold Prediction App
echo.
echo  =========================================
echo   Gold Prediction System - Starting...
echo  =========================================
echo.

rem Kill any old instance on port 5000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5000 " 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo  Loading Excel data, please wait...
echo.
start "" http://localhost:5000
"C:\Users\PC-1\AppData\Local\Programs\Python\Python38\python.exe" "%~dp0app.py"
pause
