@echo off
echo Starting MarketLens...

start "MarketLens Backend" cmd /k "cd /d C:\Users\Jeremy\ChartProject\stock-dashboard-backend && uvicorn main:app --host 0.0.0.0 --reload"
timeout /t 5 /nobreak >nul
start "MarketLens Frontend" cmd /k "cd /d C:\Users\Jeremy\ChartProject\stock-dashboard-frontend && npm run dev"

if /i "%1"=="--tunnel" (
    echo.
    echo Waiting for frontend to start...
    timeout /t 5 /nobreak >nul
    echo Starting Cloudflare Tunnel...
    start "MarketLens Tunnel" cmd /k "cloudflared tunnel --url http://localhost:5173"
)
