@echo off
echo ==============================================
echo  Starting Vecto Studio (VectoAI) on Windows...
echo ==============================================

echo -^> Starting Backend on http://127.0.0.1:8001 ...
set PYTHONPATH=.
start "Vecto Backend" cmd /c ".\backend\venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001"

echo -^> Waiting for backend to initialize...
timeout /t 3 /nobreak >nul

echo -^> Starting Frontend on http://localhost:5174 ...
cd frontend
start "Vecto Frontend" cmd /c "npm run dev"

echo -^> Opening Browser...
start http://localhost:5174
