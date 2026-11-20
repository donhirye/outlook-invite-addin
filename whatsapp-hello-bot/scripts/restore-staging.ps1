# Restore staging Cloud Run to the last known-good release (or origin/main).
#
#   .\scripts\restore-staging.ps1              # known-good record, else main
#   .\scripts\restore-staging.ps1 -FromMain    # force origin/main + baseline FAQ
#
# A bad experiment deploy can take down staging (including /admin/releases) until
# this restore completes. Production is never touched.
#
# Important: the deploy scripts run from a temp copy of *this* worktree's scripts
# so checking out an older known-good commit cannot rewind the restore tooling.

param(
  [switch]$FromMain,
  [switch]$SkipSmokeTests
)

. "$PSScriptRoot\staging-common.ps1"
Assert-StagingTarget
Assert-NotProductionTarget

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { throw "Run this from inside the git repository." }

$scriptTmp = Join-Path ([IO.Path]::GetTempPath()) ("staging-restore-scripts-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $scriptTmp | Out-Null
Copy-Item (Join-Path $PSScriptRoot "staging-common.ps1") $scriptTmp
Copy-Item (Join-Path $PSScriptRoot "deploy-staging.ps1") $scriptTmp
$deployScript = Join-Path $scriptTmp "deploy-staging.ps1"
$tmpRec = Join-Path ([IO.Path]::GetTempPath()) ("staging-known-good-" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")

Push-Location $repoRoot
try {
  $prevRef = (& git rev-parse --abbrev-ref HEAD).Trim()
  if ($prevRef -eq "HEAD") { $prevRef = (& git rev-parse HEAD).Trim() }

  $targetSha = $null
  $label = "origin/main"

  if (-not $FromMain) {
    $gcs = "gs://$($script:StagingBucket)/releases/staging-known-good.json"
    $exists = Get-GCloudOutput storage ls $gcs @StagingArgs
    if ($exists) {
      Invoke-GCloud storage cp $gcs $tmpRec @StagingArgs
      $rec = Get-Content -Raw -Path $tmpRec | ConvertFrom-Json
      if ($rec.git_sha) {
        $targetSha = [string]$rec.git_sha
        $label = "known-good $($targetSha.Substring(0,7)) (was $($rec.branch))"
      }
    }
    if (-not $targetSha) {
      Write-Host "No staging-known-good.json; using origin/main." -ForegroundColor DarkYellow
      $FromMain = $true
    }
  }

  & git fetch origin main
  if ($LASTEXITCODE -ne 0) { throw "git fetch origin main failed." }

  if ($FromMain -or -not $targetSha) {
    $targetSha = (& git rev-parse origin/main).Trim()
    $label = "origin/main $($targetSha.Substring(0,7))"
  }

  Write-Host "Restore staging from $label" -ForegroundColor Cyan
  Write-Host "  FAQ will use baseline objects (FAQ_GCS_PREFIX cleared)." -ForegroundColor Cyan
  Write-Host "  Production is not modified." -ForegroundColor Cyan

  $restoreBranch = "feature/staging-restore"
  & git checkout -B $restoreBranch $targetSha
  if ($LASTEXITCODE -ne 0) { throw "git checkout $targetSha failed." }

  try {
    $argList = @("-BaselineFaq")
    if ($SkipSmokeTests) { $argList += "-SkipSmokeTests" }
    & powershell -NoProfile -File $deployScript @argList
    if ($LASTEXITCODE -ne 0) { throw "deploy-staging.ps1 failed during restore ($LASTEXITCODE)." }
  }
  finally {
    Remove-Item -Force $tmpRec -ErrorAction SilentlyContinue
    $ErrorActionPreference = "Continue"
    & git checkout $prevRef 2>&1 | Out-Null
    $ErrorActionPreference = "Stop"
  }

  Write-Host ""
  Write-Host "Restore finished. Confirm /health, /admin/test-chat, /admin/releases." -ForegroundColor Green
}
finally {
  Remove-Item -Recurse -Force $scriptTmp -ErrorAction SilentlyContinue
  Pop-Location
}
