@echo off
echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 goto error

echo Building Beacon.exe...
pyinstaller --onefile --windowed --name Beacon --add-data "assets;assets" beacon.py
if errorlevel 1 goto error

echo.
echo Done. Distribute dist\Beacon.exe to your team.
goto end

:error
echo.
echo Build failed. See errors above.
exit /b 1

:end
