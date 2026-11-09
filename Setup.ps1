param([switch]$Build, [switch]$Dev)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 and the Windows Python launcher, then retry.' }
}
$requirements = if ($Dev) { 'requirements-dev.txt' } else { 'requirements.txt' }
& ./.venv/Scripts/python.exe -m pip install --disable-pip-version-check -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

if ($Build -or -not (Test-Path -LiteralPath 'web/dist/index.html')) {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'npm ci failed. Install Node.js 22 or newer.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
}
Write-Host 'Setup complete. Run .\Start-PitWall.ps1 -Demo or .\Start-PitWall.ps1.'
