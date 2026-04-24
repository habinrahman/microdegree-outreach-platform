$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $RepoRoot "backend"
$Frontend = Join-Path $RepoRoot "frontend"

Write-Host "Repo: $RepoRoot"
Write-Host "Starting Backend (port 8000)..."

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location -LiteralPath '$Backend'; .\venv\Scripts\Activate.ps1; uvicorn main:app --reload --port 8000"
)

Write-Host "Starting Frontend (Vite port 5173)..."
Write-Host "Open the UI at: http://127.0.0.1:5173/  (API defaults to :8010)"

Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location -LiteralPath '$Frontend'; npm run dev"
)

Write-Host "System started. Dashboard: http://127.0.0.1:5173/"