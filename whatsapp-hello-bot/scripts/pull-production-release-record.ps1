# Download the latest production-release-record artifact into the local Releases folder.
#
#   .\scripts\pull-production-release-record.ps1
#
# Read-only. Does not deploy or modify Cloud Run. Requires `gh` authenticated to the repo.

$ErrorActionPreference = "Stop"
$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { throw "Run from inside the git repository." }

$outDir = Join-Path $repoRoot "whatsapp-hello-bot\data\releases"
New-Item -ItemType Directory -Path $outDir -Force | Out-Null
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("prod-release-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmp | Out-Null

try {
  Write-Host "Finding latest successful production deploy run..."
  $runId = (& gh run list --workflow "Deploy WhatsApp bot to Cloud Run" --branch main --json databaseId,conclusion,createdAt --limit 20 |
    ConvertFrom-Json |
    Where-Object { $_.conclusion -eq "success" } |
    Select-Object -First 1).databaseId
  if (-not $runId) { throw "No successful production deploy runs found." }

  Write-Host "Downloading artifact production-release-record from run $runId"
  & gh run download $runId --name production-release-record --dir $tmp
  if ($LASTEXITCODE -ne 0) {
    throw "Artifact download failed (older runs may predate this artifact). Redeploy production once, then retry."
  }

  $found = Get-ChildItem -Path $tmp -Recurse -Filter "production-latest.json" | Select-Object -First 1
  if (-not $found) { throw "production-latest.json not found inside the artifact." }

  $dest = Join-Path $outDir "production-latest.json"
  Copy-Item -Force $found.FullName $dest
  Write-Host "Wrote $dest" -ForegroundColor Green
  Get-Content $dest
}
finally {
  Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
