$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw 'Docker is required. Install Docker Desktop, start it, then rerun this script.'
}

docker compose version | Out-Host

if (-not (Test-Path '.\config.toml')) {
  Invoke-WebRequest -UseBasicParsing `
    'https://raw.githubusercontent.com/harry0703/MoneyPrinterTurbo/main/config.example.toml' `
    -OutFile '.\config.toml'
  Write-Host 'Created config.toml from MoneyPrinterTurbo config.example.toml.'
}

if (-not (Test-Path '.\.env')) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $token = -join ($bytes | ForEach-Object { $_.ToString('x2') })
  @"
BRIDGE_HOST_BIND=127.0.0.1
BRIDGE_TOKEN=$token
MPT_HTTP_TIMEOUT=60
"@ | Set-Content -Encoding UTF8 '.\.env'
  Write-Host 'Created .env with a random bridge token.'
}

New-Item -ItemType Directory -Force '.\storage' | Out-Null

docker compose pull moneyprinter-api moneyprinter-webui
docker compose build bridge
docker compose up -d

docker compose ps
Write-Host ''
Write-Host 'WebUI:  http://127.0.0.1:8501'
Write-Host 'MPT API: http://127.0.0.1:8080/docs'
Write-Host 'Bridge:  http://127.0.0.1:8787/docs'
Write-Host ''
Write-Host 'Edit config.toml with the LLM/media API keys you intend to use, then run: docker compose restart'
