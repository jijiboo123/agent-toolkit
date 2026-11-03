@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1 && (start "" pythonw query_route.py & exit /b)
python query_route.py
pause
