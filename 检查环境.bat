@echo off
cd /d "%~dp0"
echo Checking embedded Python and dependencies...
"runtime\python\python.exe" -c "import sys; print('Python', sys.version.split()[0])"
"runtime\python\python.exe" -c "import weilink, mcp, toolregistry, fastapi, uvicorn; print('core deps OK')"
"runtime\python\python.exe" -c "import openai, numpy, sklearn, jieba; print('OB deps OK')"
"runtime\python\python.exe" -c "import bilibili_api, aiohttp; print('bili deps OK')"
echo.
echo All checks passed.
pause
