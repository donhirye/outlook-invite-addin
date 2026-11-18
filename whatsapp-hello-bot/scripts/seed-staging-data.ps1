# Copy REFERENCE data (FAQ, calendar, guided flows) from production into the staging bucket.
#
#   .\scripts\seed-staging-data.ps1 -DryRun
#   .\scripts\seed-staging-data.ps1
#
# - Production is READ-ONLY here: objects are downloaded with `gcloud storage cp` from
#   the production bucket to a temp folder. Nothing is ever written to production.
# - Only reference data is copied. Parent conversations, analytics, traces, guided
#   sessions, webhook dedupe state and engine config are NOT copied.
# - The FAQ has been confirmed to contain no personal information.
# - Uploads to staging run as the staging deployer service account.

param([switch]$DryRun)

. "$PSScriptRoot\staging-common.ps1"
Assert-StagingTarget

$prod = "gs://$script:ProdBucket"
$stg = "gs://$script:StagingBucket"
if ($stg -eq $prod -or $script:StagingBucket -notmatch "staging") { throw "Bucket mix-up; refusing." }

# Exact reference objects (no wildcards that could pick up conversation data).
$objects = @(
  "science_olympiad_faq.txt",
  "science_olympiad_faq.txt.index.json",
  "faq_records.json",
  "school_calendar.json"
)
$prefixes = @("guided/")   # guided topic definitions only (guided_state.json is NOT copied)

$tmp = Join-Path ([IO.Path]::GetTempPath()) ("seed-staging-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  foreach ($o in $objects) {
    Write-Host "copy $prod/$o -> $stg/$o"
    if ($DryRun) { continue }
    & gcloud storage cp "$prod/$o" (Join-Path $tmp $o) 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "  (not in production bucket; skipped)" -ForegroundColor Yellow; continue }
    Invoke-GCloud storage cp (Join-Path $tmp $o) "$stg/$o" @(Get-StagingArgs)
  }
  foreach ($p in $prefixes) {
    Write-Host "copy $prod/$p* -> $stg/$p"
    if ($DryRun) { continue }
    $dir = Join-Path $tmp ($p.TrimEnd("/"))
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    & gcloud storage cp "$prod/$p*" $dir 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "  (nothing to copy)" -ForegroundColor Yellow; continue }
    Invoke-GCloud storage cp (Join-Path $dir "*") "$stg/$p" @(Get-StagingArgs)
  }
}
finally {
  Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
Write-Host ""
Write-Host "Done. Staging bucket contents:" -ForegroundColor Green
if (-not $DryRun) { Invoke-GCloud storage ls $stg --recursive @(Get-StagingArgs) }
