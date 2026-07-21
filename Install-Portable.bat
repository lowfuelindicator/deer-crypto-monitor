@echo off
title Deer Crypto Monitor - portable setup
echo.
echo  Deer Crypto Monitor - portable install
echo  -------------------------------------
echo  Copies the app to %%LOCALAPPDATA%%\DeerCryptoMonitor
echo  and creates a Desktop shortcut.
echo.
pause
set "DEST=%LOCALAPPDATA%\DeerCryptoMonitor"
mkdir "%DEST%" 2>nul
xcopy /E /I /Y "%~dp0*" "%DEST%\" >nul
powershell -NoProfile -Command "=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Deer Crypto Monitor.lnk'); .TargetPath='%DEST%\DeerCryptoMonitor.exe'; .WorkingDirectory='%DEST%'; .Save()"
echo.
echo  Done. Desktop shortcut created.
echo  Launching...
start "" "%DEST%\DeerCryptoMonitor.exe"
pause
