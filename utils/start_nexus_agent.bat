@echo off
set NEXUS_API_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml5cXpnbXpseWt1ZnNidG15a3B3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNDk0OTEsImV4cCI6MjEwMDgyNTQ5MX0.OAtknQj1k5ggmHmMrlQHpQqtu9T_tl_VEpiW3DgPCng
set DEVICE_ID=victus-windows
set DEVICE_NAME=Victus (Windows Host)
set PYTHONIOENCODING=utf-8
:restart
python C:\Users\Bing\aurora\Workstation\Nexus\agent_v2.py
echo [%TIME%] Agent exited, restarting in 5s...
timeout /t 5 /nobreak >nul
goto restart
