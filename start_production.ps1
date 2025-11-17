# Production Startup Script for Support Q&A Web Interface
# Run with: .\start_production.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Support Q&A Production Server Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if virtual environment exists
if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "ERROR: Virtual environment not found!" -ForegroundColor Red
    Write-Host "Please create it first with: python -m venv venv" -ForegroundColor Yellow
    exit 1
}

# Check if .env file exists
if (-not (Test-Path ".\.env")) {
    Write-Host "WARNING: .env file not found!" -ForegroundColor Yellow
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow

    if (Test-Path ".\.env.example") {
        Copy-Item ".\.env.example" ".\.env"

        # Generate a random secret key
        $secretKey = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 64 | ForEach-Object {[char]$_})
        (Get-Content ".\.env") -replace 'SECRET_KEY=your-secret-key-here-change-this-in-production', "SECRET_KEY=$secretKey" | Set-Content ".\.env"

        Write-Host "Created .env with auto-generated SECRET_KEY" -ForegroundColor Green
        Write-Host "Please review .env file and adjust settings as needed" -ForegroundColor Yellow
    } else {
        Write-Host "ERROR: .env.example not found!" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Starting production server..." -ForegroundColor Green
Write-Host ""

# Start the server
.\venv\Scripts\python.exe web.py
