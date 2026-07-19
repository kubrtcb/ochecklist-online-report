@echo off
setlocal
cd /d %~dp0

echo Instaluji zavislosti...
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :error

echo.
echo Sestavuji OChecklistReport.exe...
pyinstaller --noconfirm --onefile --windowed --name OChecklistReport ^
    --icon favicon.ico ^
    --add-data "src\style.css;assets" ^
    --add-data "src\main.js;assets" ^
    --paths src ^
    src\gui_app.py
if errorlevel 1 goto :error

echo.
echo Hotovo! Spustitelny soubor je v dist\OChecklistReport.exe
pause
exit /b 0

:error
echo.
echo Sestaveni selhalo.
pause
exit /b 1
