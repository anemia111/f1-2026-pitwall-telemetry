param(
    [switch]$Demo,
    [switch]$Lan,
    [ValidateSet(10,20,30,60)][int]$DemoRate = 30,
    [ValidateRange(1,65535)][int]$HttpPort = 8000,
    [ValidateRange(0,65535)][int]$UdpPort = 0,
    [string]$DataPath = ''
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe') -or -not (Test-Path -LiteralPath 'web/dist/index.html')) {
    throw 'Run .\Setup.ps1 first.'
}
$launchArgs = @('-m', 'pitwall.server', '--http-port', $HttpPort)
if ($Demo) { $launchArgs += @('--demo', '--demo-rate', $DemoRate) }
if ($Lan) { $launchArgs += '--lan' }
if ($UdpPort -gt 0) { $launchArgs += @('--udp-port', $UdpPort) }
if ($DataPath) { $launchArgs += @('--data', $DataPath) }

Write-Host "Dashboard at http://127.0.0.1:$HttpPort/"
& ./.venv/Scripts/python.exe @launchArgs
exit $LASTEXITCODE
