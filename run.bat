@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Окружение Python не найдено. Выполните установку по инструкции README.md.
  pause
  exit /b 1
)
echo Откройте http://127.0.0.1:8000 в браузере. Для остановки нажмите Ctrl+C.
".venv\Scripts\python.exe" -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
