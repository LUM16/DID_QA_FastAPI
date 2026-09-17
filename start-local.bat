@echo off
setlocal
cd /d "%~dp0"
title DID Insight (local)

set "PY_EXE=C:\Program Files\Python311\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=py"

echo Installing deps...
"%PY_EXE%" -m pip install -r requirements.txt -q

echo.
echo Starting DID Insight UI at http://127.0.0.1:8010
echo Neo4j: bolt://10.109.17.64:7687
echo.

"%PY_EXE%" -m uvicorn app:app --host 127.0.0.1 --port 8010

echo.
pause
