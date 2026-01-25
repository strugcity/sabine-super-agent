@echo off
REM =============================================================================
REM Personal Super Agent - Local Development Startup Script (Windows Batch)
REM =============================================================================
REM
REM This script starts all required services in separate windows:
REM   1. ngrok tunnel (exposes port 3000 for Gmail webhooks)
REM   2. workspace-mcp server (Google Workspace MCP) - Port 8000
REM   3. Python FastAPI server (Agent API) - Port 8001
REM   4. Next.js frontend - Port 3000
REM   5. Gmail watch setup (push notifications)
REM
REM NOTE: For full automation, use start-local.ps1 (PowerShell) instead.
REM       This batch file provides basic functionality.
REM
REM =============================================================================

title Super Agent - Launcher

echo.
echo ========================================
echo  Personal Super Agent - Local Dev
echo ========================================
echo.

REM Check .env file
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Copy .env.example to .env and configure it.
    pause
    exit /b 1
)

echo [OK] .env file found
echo.

REM Check if venv exists
if not exist "venv" (
    echo [WARN] Python venv not found. Creating...
    python -m venv venv
    call venv\Scripts\pip.exe install -r requirements.txt
)

REM Check node_modules
if not exist "node_modules" (
    echo [WARN] node_modules not found. Running npm install...
    call npm install
)

REM Create logs directory
if not exist "logs" mkdir logs

echo.
echo Starting services in separate windows...
echo.

REM --- Load Google OAuth credentials from .env ---
echo [INFO] Loading Google OAuth credentials from .env...
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if "%%a"=="GOOGLE_OAUTH_CLIENT_ID" set "GOOGLE_OAUTH_CLIENT_ID=%%b"
    if "%%a"=="GOOGLE_OAUTH_CLIENT_SECRET" set "GOOGLE_OAUTH_CLIENT_SECRET=%%b"
    if "%%a"=="USER_GOOGLE_EMAIL" set "USER_GOOGLE_EMAIL=%%b"
)

if defined GOOGLE_OAUTH_CLIENT_ID (
    echo [OK] GOOGLE_OAUTH_CLIENT_ID loaded
) else (
    echo [WARN] GOOGLE_OAUTH_CLIENT_ID not found in .env
)

if defined GOOGLE_OAUTH_CLIENT_SECRET (
    echo [OK] GOOGLE_OAUTH_CLIENT_SECRET loaded
) else (
    echo [WARN] GOOGLE_OAUTH_CLIENT_SECRET not found in .env
)

if defined USER_GOOGLE_EMAIL (
    echo [OK] USER_GOOGLE_EMAIL: %USER_GOOGLE_EMAIL%
) else (
    echo [WARN] USER_GOOGLE_EMAIL not found in .env
)

echo.

REM --- 0. Start ngrok tunnel ---
echo [INFO] Starting ngrok tunnel (Port 3000)...
where ngrok >nul 2>&1
if %errorlevel% equ 0 (
    start "ngrok - Port 3000" cmd /k "ngrok http 3000"
    echo [OK] ngrok starting...
    echo [INFO] After ngrok starts, run: python scripts\setup_gmail_watch.py --ngrok-url YOUR_NGROK_URL
    timeout /t 3 /nobreak > nul
) else (
    echo [WARN] ngrok not found. Gmail webhooks won't work without it.
    echo [WARN] Install from: https://ngrok.com/download
)

echo.

REM --- 1. Start MCP Server ---
echo [INFO] Starting workspace-mcp server (Port 8000)...

REM Try to find workspace-mcp in common locations
set "MCP_EXE="
if exist "%APPDATA%\Python\Python313\Scripts\workspace-mcp.exe" (
    set "MCP_EXE=%APPDATA%\Python\Python313\Scripts\workspace-mcp.exe"
) else if exist "%APPDATA%\Python\Python312\Scripts\workspace-mcp.exe" (
    set "MCP_EXE=%APPDATA%\Python\Python312\Scripts\workspace-mcp.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python313\Scripts\workspace-mcp.exe" (
    set "MCP_EXE=%LOCALAPPDATA%\Programs\Python\Python313\Scripts\workspace-mcp.exe"
)

if defined MCP_EXE (
    echo [OK] Found workspace-mcp at: %MCP_EXE%
    REM Start MCP server with Google OAuth env vars and HTTP transport mode
    start "MCP Server - Port 8000" cmd /k "set GOOGLE_OAUTH_CLIENT_ID=%GOOGLE_OAUTH_CLIENT_ID% && set GOOGLE_OAUTH_CLIENT_SECRET=%GOOGLE_OAUTH_CLIENT_SECRET% && set USER_GOOGLE_EMAIL=%USER_GOOGLE_EMAIL% && "%MCP_EXE%" --transport streamable-http"
    timeout /t 2 /nobreak > nul
) else (
    echo [WARN] workspace-mcp not found. Install with: pip install workspace-mcp
    echo [WARN] Continuing without MCP server...
)

REM --- 2. Start Python API ---
echo [INFO] Starting Python FastAPI server (Port 8001)...
start "Python API - Port 8001" cmd /k "venv\Scripts\activate && python lib\agent\server.py"

REM Wait a moment for Python to start
timeout /t 3 /nobreak > nul

REM --- 3. Start Next.js ---
echo [INFO] Starting Next.js frontend (Port 3000)...
start "Next.js - Port 3000" cmd /k "npm run dev"

echo.
echo ========================================
echo  Services Starting!
echo ========================================
echo.
echo   Frontend:     http://localhost:3000
echo   Agent API:    http://localhost:8001
echo   API Docs:     http://localhost:8001/docs
echo   MCP Server:   http://localhost:8000/mcp
echo   ngrok:        Check ngrok window for public URL
echo.
echo IMPORTANT: After ngrok starts, run Gmail watch setup:
echo   python scripts\setup_gmail_watch.py --ngrok-url https://YOUR-NGROK-URL
echo.
echo Close the service windows to stop them.
echo.

pause
