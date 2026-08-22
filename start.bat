@echo off
REM ===================================================================
REM  InsightFlow - one-click local start (Windows)
REM
REM  Opens two terminal windows:
REM    - Backend  (FastAPI/uvicorn) on http://127.0.0.1:8000
REM    - Frontend (Vite dev server) on http://127.0.0.1:5173
REM
REM  Close either window to stop that server.
REM ===================================================================

setlocal
set "ROOT=%~dp0"

echo.
echo  InsightFlow - starting local development servers
echo  ------------------------------------------------

REM --- sanity checks -------------------------------------------------
if not exist "%ROOT%backend\app\main.py" (
  echo  ERROR: backend\app\main.py not found.
  echo  Run this script from the InsightFlow project folder.
  pause
  exit /b 1
)

if not exist "%ROOT%frontend\node_modules" (
  echo  Frontend dependencies are missing. Installing now...
  pushd "%ROOT%frontend"
  call npm install
  popd
  echo.
)

REM --- first run: create a .env so JWT_SECRET is stable -------------
REM  Without this the backend generates a throwaway secret on every
REM  boot, which silently invalidates any token you already had.
if not exist "%ROOT%backend\.env" (
  echo  No backend\.env found - creating one for local development.
  > "%ROOT%backend\.env" echo ENVIRONMENT=development
  >> "%ROOT%backend\.env" echo DEBUG=true
  >> "%ROOT%backend\.env" echo JWT_SECRET=local-dev-secret-change-me-in-production
  >> "%ROOT%backend\.env" echo DATABASE_URL=sqlite:///./insightflow.db
  >> "%ROOT%backend\.env" echo CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
  echo  Created backend\.env
  echo.
)

REM --- launch --------------------------------------------------------
echo  Backend  -^> http://127.0.0.1:8000        (API docs at /docs)
echo  Frontend -^> http://127.0.0.1:5173        (open this one)
echo.

start "InsightFlow Backend" cmd /k "cd /d "%ROOT%backend" && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start "InsightFlow Frontend" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo  Both servers are starting in separate windows.
echo  Give them a few seconds, then open:  http://127.0.0.1:5173
echo.
timeout /t 6 /nobreak >nul
start "" "http://127.0.0.1:5173"

endlocal
