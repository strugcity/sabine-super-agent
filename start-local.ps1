# =============================================================================
# Personal Super Agent - Local Development Startup Script (Windows PowerShell)
# =============================================================================
#
# This script starts all required services for local development:
#   1. ngrok tunnel (exposes port 3000 for Gmail webhooks)
#   2. workspace-mcp server (Google Workspace MCP) - Port 8000
#   3. Python FastAPI server (Agent API) - Port 8001
#   4. Next.js frontend - Port 3000
#   5. Gmail watch setup (push notifications)
#
# Usage:
#   .\start-local.ps1              # Start all services
#   .\start-local.ps1 -SkipMcp     # Start without MCP server
#   .\start-local.ps1 -SkipNgrok   # Start without ngrok tunnel
#   .\start-local.ps1 -SkipGmail   # Skip Gmail watch setup
#
# =============================================================================

param(
    [switch]$SkipMcp,
    [switch]$SkipNgrok,
    [switch]$SkipGmail,
    [switch]$Help
)

if ($Help) {
    Write-Host @"
Personal Super Agent - Local Development Startup

USAGE:
    .\start-local.ps1              Start all services
    .\start-local.ps1 -SkipMcp     Start without MCP server (if running externally)
    .\start-local.ps1 -SkipNgrok   Start without ngrok tunnel
    .\start-local.ps1 -SkipGmail   Skip Gmail watch setup
    .\start-local.ps1 -Help        Show this help message

SERVICES STARTED:
    1. ngrok (Port 3000 tunnel)  - Exposes local server for webhooks
    2. workspace-mcp (Port 8000) - Google Workspace integration via MCP
    3. Python API (Port 8001)    - FastAPI agent server
    4. Next.js (Port 3000)       - Frontend and webhooks
    5. Gmail Watch               - Push notification setup

PREREQUISITES:
    - Node.js 18+
    - Python 3.11+
    - ngrok (for Gmail webhooks)
    - npm packages installed (npm install)
    - Python packages installed (pip install -r requirements.txt)

URLS:
    Frontend:    http://localhost:3000
    Agent API:   http://localhost:8001
    API Docs:    http://localhost:8001/docs
    MCP Server:  http://localhost:8000/mcp
"@
    exit 0
}

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Info { Write-Host "[INFO] $args" -ForegroundColor Cyan }
function Write-Success { Write-Host "[OK] $args" -ForegroundColor Green }
function Write-Warn { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err { Write-Host "[ERROR] $args" -ForegroundColor Red }

# Get script directory
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host " Personal Super Agent - Local Dev" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta
Write-Host ""

# =============================================================================
# Pre-flight Checks
# =============================================================================

Write-Info "Running pre-flight checks..."

# Check Node.js
try {
    $nodeVersion = node --version
    Write-Success "Node.js $nodeVersion"
} catch {
    Write-Err "Node.js not found. Please install Node.js 18+"
    exit 1
}

# Check Python
try {
    $pythonVersion = python --version
    Write-Success "Python $pythonVersion"
} catch {
    Write-Err "Python not found. Please install Python 3.11+"
    exit 1
}

# Check ngrok (optional but warn if missing)
if (-not $SkipNgrok) {
    try {
        $ngrokPath = Get-Command ngrok -ErrorAction SilentlyContinue
        if ($ngrokPath) {
            Write-Success "ngrok found"
        } else {
            Write-Warn "ngrok not found. Gmail webhooks won't work without it."
            Write-Warn "Install from: https://ngrok.com/download"
            $SkipNgrok = $true
        }
    } catch {
        Write-Warn "ngrok not found. Gmail webhooks won't work without it."
        $SkipNgrok = $true
    }
}

# Check .env file
if (-not (Test-Path ".env")) {
    Write-Err ".env file not found. Copy .env.example to .env and configure it."
    exit 1
}
Write-Success ".env file found"

# Check AGENT_API_KEY is set
$envContent = Get-Content ".env" -Raw
if ($envContent -notmatch "AGENT_API_KEY=.+") {
    Write-Err "AGENT_API_KEY not set in .env file. This is required for security."
    exit 1
}
Write-Success "AGENT_API_KEY configured"

# Check node_modules
if (-not (Test-Path "node_modules")) {
    Write-Warn "node_modules not found. Running npm install..."
    npm install
}

# Check Python venv
if (-not (Test-Path "venv")) {
    Write-Warn "Python venv not found. Creating..."
    python -m venv venv
    & ".\venv\Scripts\pip.exe" install -r requirements.txt
}

Write-Host ""

# =============================================================================
# Kill existing processes on our ports
# =============================================================================

Write-Info "Checking for existing processes..."

# Kill any existing Python processes from our venv
$pythonProcs = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like "*superAgent*"
}
if ($pythonProcs) {
    Write-Warn "Killing existing Python processes..."
    $pythonProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

# Kill processes on specific ports
$ports = @(3000, 8000, 8001)
foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    $pids = $connections | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -ne 0 }
    foreach ($pid in $pids) {
        try {
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Warn "Port $port in use by PID $pid ($($proc.ProcessName)) - killing..."
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            }
        } catch {
            # Process may have already exited
        }
    }
}

# Also kill any existing ngrok processes
$ngrokProcs = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
if ($ngrokProcs) {
    Write-Warn "Killing existing ngrok process..."
    $ngrokProcs | Stop-Process -Force -ErrorAction SilentlyContinue
}

# Wait for ports to be fully released
Write-Info "Waiting for ports to be released..."
Start-Sleep -Seconds 2

Write-Host ""

# =============================================================================
# Create logs directory
# =============================================================================

if (-not (Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

# =============================================================================
# Start Services
# =============================================================================

$jobs = @()
$ngrokUrl = $null

# --- Load Google OAuth credentials from .env ---
Write-Info "Loading Google OAuth credentials from .env..."

$googleOAuthClientId = $null
$googleOAuthClientSecret = $null
$userGoogleEmail = $null

Get-Content ".env" | ForEach-Object {
    if ($_ -match "^GOOGLE_OAUTH_CLIENT_ID=(.+)$") { $googleOAuthClientId = $matches[1] }
    if ($_ -match "^GOOGLE_OAUTH_CLIENT_SECRET=(.+)$") { $googleOAuthClientSecret = $matches[1] }
    if ($_ -match "^USER_GOOGLE_EMAIL=(.+)$") { $userGoogleEmail = $matches[1] }
}

if ($googleOAuthClientId) { Write-Success "GOOGLE_OAUTH_CLIENT_ID loaded" }
else { Write-Warn "GOOGLE_OAUTH_CLIENT_ID not found in .env" }

if ($googleOAuthClientSecret) { Write-Success "GOOGLE_OAUTH_CLIENT_SECRET loaded" }
else { Write-Warn "GOOGLE_OAUTH_CLIENT_SECRET not found in .env" }

if ($userGoogleEmail) { Write-Success "USER_GOOGLE_EMAIL: $userGoogleEmail" }
else { Write-Warn "USER_GOOGLE_EMAIL not found in .env" }

Write-Host ""

# --- 0. Start ngrok tunnel ---
if (-not $SkipNgrok) {
    Write-Info "Starting ngrok tunnel (Port 3000)..."

    # Start ngrok in background
    $ngrokJob = Start-Job -Name "ngrok" -ScriptBlock {
        Set-Location $using:ScriptDir
        ngrok http 3000 --log=stdout 2>&1 | Tee-Object -FilePath "logs\ngrok.log"
    }
    $jobs += $ngrokJob

    # Wait for ngrok to start and get the public URL
    Write-Info "Waiting for ngrok to establish tunnel..."
    Start-Sleep -Seconds 3

    # Try to get ngrok URL from API
    $maxRetries = 10
    for ($i = 0; $i -lt $maxRetries; $i++) {
        try {
            $ngrokApi = Invoke-RestMethod -Uri "http://127.0.0.1:4040/api/tunnels" -ErrorAction SilentlyContinue
            if ($ngrokApi.tunnels.Count -gt 0) {
                $ngrokUrl = ($ngrokApi.tunnels | Where-Object { $_.proto -eq "https" } | Select-Object -First 1).public_url
                if ($ngrokUrl) {
                    Write-Success "ngrok tunnel: $ngrokUrl"
                    break
                }
            }
        } catch {
            # ngrok API not ready yet
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $ngrokUrl) {
        Write-Warn "Could not get ngrok URL. Check logs\ngrok.log"
        Write-Warn "You may need to authenticate ngrok: ngrok config add-authtoken <token>"
    }

    Write-Host ""
} else {
    Write-Info "Skipping ngrok (-SkipNgrok flag)"
    Write-Host ""
}

# --- 1. MCP Server (workspace-mcp) ---
if (-not $SkipMcp) {
    Write-Info "Starting workspace-mcp server (Port 8000)..."

    # Check multiple possible locations for workspace-mcp
    $mcpPaths = @(
        "workspace-mcp",  # If in PATH
        "$env:APPDATA\Python\Python313\Scripts\workspace-mcp.exe",
        "$env:APPDATA\Python\Python312\Scripts\workspace-mcp.exe",
        "$env:APPDATA\Python\Python311\Scripts\workspace-mcp.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\Scripts\workspace-mcp.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\workspace-mcp.exe"
    )

    $mcpExe = $null
    foreach ($path in $mcpPaths) {
        if (Get-Command $path -ErrorAction SilentlyContinue) {
            $mcpExe = $path
            break
        }
        if (Test-Path $path) {
            $mcpExe = $path
            break
        }
    }

    if ($mcpExe) {
        Write-Info "Found workspace-mcp at: $mcpExe"
        # Pass Google OAuth credentials to the MCP server job with HTTP transport
        $mcpJob = Start-Job -Name "MCP" -ScriptBlock {
            Set-Location $using:ScriptDir
            # Set environment variables for Google OAuth
            $env:GOOGLE_OAUTH_CLIENT_ID = $using:googleOAuthClientId
            $env:GOOGLE_OAUTH_CLIENT_SECRET = $using:googleOAuthClientSecret
            $env:USER_GOOGLE_EMAIL = $using:userGoogleEmail
            # Start with streamable-http transport for HTTP API access
            & $using:mcpExe --transport streamable-http 2>&1 | Tee-Object -FilePath "logs\mcp-server.log"
        }
        $jobs += $mcpJob
        Write-Success "workspace-mcp starting... (logs: logs\mcp-server.log)"

        # Wait for MCP server to be ready before starting Python
        Write-Info "Waiting for MCP server to be ready..."
        $mcpReady = $false
        for ($i = 0; $i -lt 10; $i++) {
            Start-Sleep -Seconds 1
            try {
                $response = Invoke-WebRequest -Uri "http://localhost:8000/mcp" -Method Post -Body '{"jsonrpc":"2.0","id":"test","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}' -ContentType "application/json" -TimeoutSec 2 -ErrorAction SilentlyContinue
                if ($response.StatusCode -eq 200) {
                    Write-Success "MCP server is ready"
                    $mcpReady = $true
                    break
                }
            } catch {
                # MCP not ready yet
            }
        }
        if (-not $mcpReady) {
            Write-Warn "MCP server may not be ready, continuing anyway..."
        }
    } else {
        Write-Warn "workspace-mcp not found. Install with: pip install workspace-mcp"
        Write-Warn "Continuing without MCP server..."
    }
} else {
    Write-Info "Skipping MCP server (-SkipMcp flag)"
}

# --- 2. Python FastAPI Server ---
Write-Info "Starting Python FastAPI server (Port 8001)..."

$pythonJob = Start-Job -Name "Python" -ScriptBlock {
    Set-Location $using:ScriptDir
    & ".\venv\Scripts\python.exe" "lib\agent\server.py" 2>&1 | Tee-Object -FilePath "logs\python-api.log"
}
$jobs += $pythonJob
Write-Success "Python API starting... (logs: logs\python-api.log)"

Start-Sleep -Seconds 3

# --- 3. Next.js Frontend ---
Write-Info "Starting Next.js frontend (Port 3000)..."

$nextJob = Start-Job -Name "NextJS" -ScriptBlock {
    Set-Location $using:ScriptDir
    npm run dev 2>&1 | Tee-Object -FilePath "logs\nextjs.log"
}
$jobs += $nextJob
Write-Success "Next.js starting... (logs: logs\nextjs.log)"

Start-Sleep -Seconds 3

# --- 4. Setup Gmail Watch ---
if (-not $SkipGmail -and $ngrokUrl) {
    Write-Host ""
    Write-Info "Setting up Gmail watch with ngrok URL..."

    try {
        # Update .env and setup Gmail watch
        & ".\venv\Scripts\python.exe" "scripts\setup_gmail_watch.py" --ngrok-url $ngrokUrl 2>&1 | ForEach-Object {
            if ($_ -match "SUCCESS|Expires on") {
                Write-Success $_
            } elseif ($_ -match "ERROR") {
                Write-Err $_
            } else {
                Write-Host "  $_" -ForegroundColor Gray
            }
        }
    } catch {
        Write-Warn "Gmail watch setup failed: $_"
        Write-Warn "You can run manually: python scripts\setup_gmail_watch.py --ngrok-url $ngrokUrl"
    }
} elseif (-not $SkipGmail -and -not $ngrokUrl) {
    Write-Warn "Skipping Gmail watch setup (no ngrok URL available)"
} else {
    Write-Info "Skipping Gmail watch setup (-SkipGmail flag)"
}

# =============================================================================
# Summary
# =============================================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " All Services Started!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend:     http://localhost:3000" -ForegroundColor White
Write-Host "  Agent API:    http://localhost:8001" -ForegroundColor White
Write-Host "  API Docs:     http://localhost:8001/docs" -ForegroundColor White
if (-not $SkipMcp) {
    Write-Host "  MCP Server:   http://localhost:8000/mcp" -ForegroundColor White
}
if ($ngrokUrl) {
    Write-Host ""
    Write-Host "  Public URL:   $ngrokUrl" -ForegroundColor Cyan
    Write-Host "  Gmail Hook:   $ngrokUrl/api/gmail/webhook" -ForegroundColor Cyan
}
Write-Host ""
Write-Host "  Logs directory: .\logs\" -ForegroundColor Gray
Write-Host ""
Write-Host "Press Ctrl+C to stop all services..." -ForegroundColor Yellow
Write-Host ""

# =============================================================================
# Wait and Monitor
# =============================================================================

try {
    while ($true) {
        # Check if any jobs have failed or completed unexpectedly
        foreach ($job in $jobs) {
            if ($job.State -eq "Failed" -or $job.State -eq "Completed") {
                Write-Err "$($job.Name) has stopped (State: $($job.State))!"
                # Get job output without file locking issues
                try {
                    $output = Receive-Job $job -ErrorAction SilentlyContinue 2>&1
                    if ($output) {
                        Write-Host "Output: $($output | Select-Object -Last 5)" -ForegroundColor Gray
                    }
                } catch {
                    Write-Warn "Could not retrieve job output: $_"
                }
                # Exit the loop to trigger cleanup
                throw "Service $($job.Name) has stopped"
            }
        }
        Start-Sleep -Seconds 5
    }
} finally {
    Write-Host ""
    Write-Info "Shutting down services..."

    # Stop all jobs
    foreach ($job in $jobs) {
        Write-Info "Stopping $($job.Name)..."
        Stop-Job $job -ErrorAction SilentlyContinue
        Remove-Job $job -ErrorAction SilentlyContinue
    }

    # Kill ngrok process
    $ngrokProcs = Get-Process -Name "ngrok" -ErrorAction SilentlyContinue
    if ($ngrokProcs) {
        Write-Info "Stopping ngrok..."
        $ngrokProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    }

    # Kill any remaining processes on our ports
    foreach ($port in $ports) {
        $process = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
                   Select-Object -ExpandProperty OwningProcess -Unique
        if ($process) {
            Stop-Process -Id $process -Force -ErrorAction SilentlyContinue
        }
    }

    Write-Success "All services stopped."
}
