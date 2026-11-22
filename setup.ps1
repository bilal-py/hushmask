# One-step setup on Windows:  .\setup.ps1          (add -Names for the local names model, ~1.7 GB)
# Then:                        uv run hushmask serve --open
param([switch]$Names)
$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (Python package manager)..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

$extras = @("--extra", "proxy")
if ($Names) { $extras += @("--extra", "ner") }
Write-Host "Installing hushmask..."
uv sync @extras

if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host "Building the dashboard..."
    Push-Location web
    npm ci --no-audit --no-fund
    npm run build
    Pop-Location
} else {
    Write-Host "Node.js not found: skipping the dashboard. The proxy and CLI still work. Install Node 20+ and re-run for the dashboard."
}

Write-Host ""
Write-Host "Done. Start it with:  uv run hushmask serve --open"
if (-not $Names) { Write-Host "For names nobody listed, re-run with:  .\setup.ps1 -Names" }
