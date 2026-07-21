@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:5130
where python >nul 2>nul
if %errorlevel%==0 (
  python app.py
) else (
  "C:\Users\Windows\AppData\Local\Programs\Python\Python311\python.exe" app.py
)
pause
