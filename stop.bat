@echo off
echo Stopping VectoAI...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8001" ^| findstr "LISTENING"') do (
    echo Killing backend PID %%a
    taskkill /f /pid %%a
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5174" ^| findstr "LISTENING"') do (
    echo Killing frontend PID %%a
    taskkill /f /pid %%a
)
echo Done!
