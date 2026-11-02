# FraudShield – one-step local setup for Windows (PowerShell 5.1+).
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Safe to run again: it never overwrites an existing backend\.env and never deletes data.
# Needs Python 3.11+, Node 18+ and a running MySQL 8 server.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
function Require($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd was not found. $hint" }
}
function NewSecret { -join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }) }

Require 'python' 'Install Python 3.11+ from https://www.python.org and tick "Add to PATH".'
Require 'npm' 'Install Node.js 18+ from https://nodejs.org.'

Step 'Backend: virtual environment and dependencies'
$py = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { python -m venv (Join-Path $backend '.venv') }
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r (Join-Path $backend 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'pip install failed.' }

Step 'Backend: configuration (backend\.env)'
$envFile = Join-Path $backend '.env'
if (Test-Path $envFile) {
    Write-Host 'backend\.env already exists - left unchanged.'
} else {
    $dbHost = Read-Host 'MySQL host [localhost]'; if (-not $dbHost) { $dbHost = 'localhost' }
    $dbPort = Read-Host 'MySQL port [3306]'; if (-not $dbPort) { $dbPort = '3306' }
    $dbUser = Read-Host 'MySQL user [root]'; if (-not $dbUser) { $dbUser = 'root' }
    $secure = Read-Host 'MySQL password' -AsSecureString
    $dbPass = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    $dbName = Read-Host 'Database name [bank]'; if (-not $dbName) { $dbName = 'bank' }
    $encoded = [Uri]::EscapeDataString($dbPass)
    $content = Get-Content (Join-Path $backend '.env.example') -Raw
    $content = $content -replace '(?m)^DATABASE_URL=.*$', "DATABASE_URL=mysql+pymysql://${dbUser}:${encoded}@${dbHost}:${dbPort}/${dbName}?charset=utf8mb4"
    $content = $content -replace '(?m)^SECRET_KEY=.*$', "SECRET_KEY=$(NewSecret)"
    $content = $content -replace '(?m)^JWT_SECRET_KEY=.*$', "JWT_SECRET_KEY=$(NewSecret)"
    $content = $content -replace '(?m)^CORS_ORIGINS=.*$', 'CORS_ORIGINS=http://localhost:3000,http://localhost:5173'
    [IO.File]::WriteAllText($envFile, $content, (New-Object Text.UTF8Encoding $false))
    Write-Host 'Created backend\.env (random secret keys; dummy logins from .env.example).'
}

Step 'Database: create it if missing, then run every migration and seeder'
Push-Location $backend
try {
    & $py -m flask --app app.py init-db
    if ($LASTEXITCODE -ne 0) { throw 'Database setup failed - check DATABASE_URL in backend\.env.' }
} finally { Pop-Location }

Step 'Frontend: dependencies'
Push-Location $frontend
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
} finally { Pop-Location }

Step 'Done'
Write-Host @"
Start the app in two terminals:
  backend : cd backend;  .\.venv\Scripts\python.exe app.py     (http://127.0.0.1:5000)
  frontend: cd frontend; npm run dev                            (http://localhost:3000)
Run the tests: cd backend; .\.venv\Scripts\python.exe -m pytest -q
Dummy logins are listed in README.md (section 2) and set in backend\.env.
"@
