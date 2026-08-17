@echo off
rem OpenCompanion 一键工具箱（推送+构建 / 清理缓存 / 清理用户数据）
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\pushbuild.ps1"
echo.
pause