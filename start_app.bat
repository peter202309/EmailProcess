@echo off
echo Starting AI Mailguard...

:: Start Backend
echo Starting Backend (Python FastAPI)...
start "AI Mailguard Backend" cmd /k "cd backend && python main.py"

:: Wait a moment for backend to initialize
timeout /t 3 /nobreak >nul

:: Start Frontend
echo Starting Frontend (Vite)...
start "AI Mailguard Frontend" cmd /k "npm run dev"

echo Done! Services are running in separate windows.
echo Frontend: http://localhost:5173
echo Backend: http://localhost:8000
