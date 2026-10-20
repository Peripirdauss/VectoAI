@echo off
echo ==============================================
echo  Starting Tunnel for Vecto Studio
echo ==============================================
echo.
echo Please ensure the frontend is running (e.g. by running run.bat).
echo This tunnel will expose the frontend (port 5174) to the internet.
echo.
echo Choose your tunnel provider:
echo [1] localtunnel (requires npx, fast to start)
echo [2] cloudflared (requires cloudflared, very stable)
echo.
set /p choice=Enter 1 or 2: 

if "%choice%"=="1" (
    echo.
    echo Starting localtunnel...
    echo Note: The URL will be printed below.
    call npx localtunnel --port 5174
) else if "%choice%"=="2" (
    echo.
    echo Starting cloudflared...
    echo Note: Look for the URL ending with "trycloudflare.com" below.
    cloudflared tunnel --url http://localhost:5174
) else (
    echo Invalid choice.
)
pause
