@echo off
set NEXUS_API_KEY=${NEXUS_SECRET_FROM_ENV}
set DEVICE_ID=victus-windows
set DEVICE_NAME=Victus (Windows Host)
set PYTHONIOENCODING=utf-8
:restart
python C:\Users\Bing\aurora\Workstation\Nexus\agent_v2.py
echo [%TIME%] Agent exited, restarting in 5s...
timeout /t 5 /nobreak >nul
goto restart

