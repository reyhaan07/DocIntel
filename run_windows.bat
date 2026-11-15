@echo off
rem docintel - set up (first time only) and start the web app, then open the browser.
setlocal
cd /d "%~dp0"
title docintel

set "PY=python"
where python >nul 2>nul || (
  where py >nul 2>nul && (set "PY=py -3") || (
    echo Python 3.10 or newer is needed: https://www.python.org/downloads/
    echo In the installer, tick "Add python.exe to PATH". Then run this file again.
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Setting up docintel for the first time - this takes a minute or two...
  %PY% -m venv .venv || (echo Could not create the Python environment. & pause & exit /b 1)
)
call ".venv\Scripts\activate.bat"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e . || (echo Installing docintel failed - see the messages above. & pause & exit /b 1)

rem Tesseract reads scans and photos; the Windows installer puts it here by default
where tesseract >nul 2>nul || (
  if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "PATH=%PATH%;C:\Program Files\Tesseract-OCR"
)
where tesseract >nul 2>nul || (
  echo.
  echo Note: Tesseract OCR was not found - scanned pages and photos will be marked "Needs OCR".
  echo Install it from https://github.com/UB-Mannheim/tesseract/wiki to read them.
  echo.
)

echo.
echo docintel is starting at http://localhost:8000  - close this window to stop it.
echo.
start "" cmd /c "timeout /t 6 /nobreak >nul & start http://localhost:8000"
python -m docintel serve
pause
