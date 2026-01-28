@echo off
echo Starting AI Mailguard...

:: Start Backend
echo Starting Backend (Python FastAPI)...
start "AI Mailguard Backend" cmd /k "cd backend && .\venv\Scripts\python.exe main.py"

:: Wait a moment for backend to initialize
timeout /t 3 /nobreak >nul

:: Start Frontend
echo Starting Frontend (Vite)...
start "AI Mailguard Frontend" cmd /k "npm run dev"

echo Done! Services are running in separate windows.
echo Frontend: http://localhost:5180
echo Backend: http://localhost:8010
