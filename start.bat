@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  echo Сначала выполни установку из README.md
  pause
  exit /b
)
call .venv\Scripts\activate.bat
python main.py
pause
