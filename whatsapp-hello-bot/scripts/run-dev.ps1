# Start local DEV (laptop-only). Never loads whatsapp-hello-bot/.env (prod/staging secrets).
#
#   .\scripts\run-dev.ps1
#   .\scripts\run-dev.ps1 -Seed
#
# Binds to 127.0.0.1:8000. Stop with Ctrl+C.

param(
  [switch]$Seed,
  [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$appRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $appRoot
Set-Location $appRoot

$envExample = Join-Path $appRoot ".env.development.example"
$envFile = Join-Path $appRoot ".env.development"
if (-not (Test-Path $envFile)) {
  if (-not (Test-Path $envExample)) { throw "Missing .env.development.example" }
  Copy-Item $envExample $envFile
  Write-Host "Created .env.development from example." -ForegroundColor Yellow
  Write-Host "ACTION REQUIRED: edit .env.development and set OPENAI_API_KEY to a DEV-only key, then re-run." -ForegroundColor Yellow
  exit 2
}

# Scrub inherited cloud / WhatsApp / OpenAI secrets from this process.
foreach ($name in @(
    "FAQ_GCS_BUCKET", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
    "OPENAI_API_KEY", "ADMIN_PASSWORD", "SECRET_KEY", "GOOGLE_APPLICATION_CREDENTIALS"
  )) {
  Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
}

$env:APP_ENV = "development"
$env:DOTENV_PATH = $envFile
$env:FAQ_GCS_BUCKET = ""

$py = Join-Path $appRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Create the venv first: py -m venv .venv && .venv\Scripts\pip install -r requirements.txt" }

if ($Seed -or -not (Test-Path (Join-Path $appRoot "data\dev\faq_records.json"))) {
  Write-Host "Seeding data/dev from shared data (sanitized)..." -ForegroundColor Cyan
  & $py (Join-Path $PSScriptRoot "seed-dev-data.py")
  if ($LASTEXITCODE -ne 0) { throw "seed-dev-data.py failed" }
}

# Confirm key present without printing it.
$keyLine = Get-Content $envFile | Where-Object { $_ -match '^\s*OPENAI_API_KEY\s*=' } | Select-Object -First 1
if (-not $keyLine -or $keyLine -match '^\s*OPENAI_API_KEY\s*=\s*$' -or $keyLine -match 'YOUR_OPENAI') {
  Write-Host "ACTION REQUIRED: set OPENAI_API_KEY in .env.development to a separate DEV OpenAI key." -ForegroundColor Yellow
  exit 2
}

Write-Host "LOCAL DEV" -ForegroundColor Cyan
Write-Host "  APP_ENV=development"
Write-Host "  dotenv = $envFile"
Write-Host "  data   = $appRoot\data\dev"
Write-Host "  bind   = 127.0.0.1:$Port"
Write-Host "  url    = http://127.0.0.1:$Port/admin"
Write-Host "Stop with Ctrl+C"
Write-Host ""

& $py -m uvicorn app.main:app --reload --host 127.0.0.1 --port $Port
