@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYW="
if exist "runtime\python\python.exe" (
    "runtime\python\python.exe" -c "import tkinter; r=tkinter.Tk(); r.destroy()" >nul 2>&1
    if not errorlevel 1 set "PYW=runtime\python\pythonw.exe"
)
if not defined PYW if exist "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe" set "PYW=C:\Users\Administrator\AppData\Local\Programs\Python\Python311\pythonw.exe"
if not defined PYW set "PYW=pythonw"

start "" "%PYW%" "scripts\launcher.py"
exit /b 0
