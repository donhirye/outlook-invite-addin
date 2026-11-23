# Deploy the CURRENT COMMIT of this repo to the STAGING Cloud Run service.
#
#   .\scripts\deploy-staging.ps1
#
# - Target is hard-coded: project vi1234-staging, service whatsapp-faq-bot-staging.
#   There is no option to deploy to production (production deploys only via the
#   GitHub Actions workflow, with approval).
# - Deploys exactly what is committed (git archive HEAD), never the working folder,
#   so what you test is what is recorded in Git. Uncommitted tracked changes -> refused.
# - Records branch, full commit SHA, deploy time, serving revision and image digest on
#   Cloud Run (env + labels) and in gs://…/releases/staging-latest.json.
# - "What's live" = the revision with traffic (not merely latest created).
# - Runs as the staging-only deployer service account (impersonation).
# - Staging secrets come from Secret Manager in the staging project.

param(
  [switch]$SkipSmokeTests
)

. "$PSScriptRoot\staging-common.ps1"
Assert-StagingTarget

$repoRoot = (& git rev-parse --show-toplevel).Trim()
if (-not $repoRoot) { throw "Run this from inside the git repository." }
Push-Location $repoRoot
try {
  $dirty = (& git status --porcelain --untracked-files=no | Out-String).Trim()
  if ($dirty) {
    throw "Uncommitted changes to tracked files. Commit them first (staging deploys the commit, not the folder):`n$dirty"
  }
  $branch = (& git rev-parse --abbrev-ref HEAD).Trim()
  $sha = (& git rev-parse HEAD).Trim()
  $shortSha = $sha.Substring(0, 7)
  $branchLabel = Get-LabelSafeSlug -Value $branch
  $appDir = "whatsapp-hello-bot"
  if (-not (Test-Path (Join-Path $repoRoot "$appDir\Dockerfile"))) {
    throw "Expected $appDir\Dockerfile under $repoRoot."
  }

  Write-Host "Staging deploy" -ForegroundColor Cyan
  Write-Host "  project : $script:StagingProject"
  Write-Host "  service : $script:StagingService ($script:Region)"
  Write-Host "  runs as : $script:DeployerSa (impersonated)"
  Write-Host "  commit  : $sha"
  Write-Host "  branch  : $branch"

  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("staging-deploy-" + $shortSha + "-" + [guid]::NewGuid().ToString("N").Substring(0, 6))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  $zip = "$tmp.zip"
  try {
    & git archive --format=zip -o $zip "HEAD:$appDir"
    if ($LASTEXITCODE -ne 0) { throw "git archive failed." }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force

    # --update-env-vars merges; does not wipe unrelated existing env (e.g. base URLs).
    # OPENAI_MODEL matches production (gpt-5-mini) so staging answers are comparable.
    $envVars = @(
      "APP_ENV=staging",
      "FAQ_GCS_BUCKET=$script:StagingBucket",
      "FAQ_ADMIN_PHONES=$script:StagingAdminPhones",
      "OPENAI_MODEL=gpt-5-mini",
      "GIT_SHA=$sha",
      "DEPLOY_BRANCH=$branch"
    ) -join ","
    $secrets = @(
      "ADMIN_PASSWORD=$($script:SecretAdminPassword):latest",
      "SECRET_KEY=$($script:SecretSecretKey):latest",
      "OPENAI_API_KEY=$($script:SecretOpenAiKey):latest"
    ) -join ","
    $labels = "env=staging,git-sha=$shortSha,git-branch=$branchLabel"

    # WhatsApp tokens are intentionally never set on staging.
    Invoke-GCloud run deploy $script:StagingService `
      @StagingArgs `
      "--region=$script:Region" `
      "--source=$tmp" `
      "--service-account=$script:RuntimeSa" `
      "--allow-unauthenticated" `
      "--min-instances=0" `
      "--max-instances=2" `
      "--update-env-vars=$envVars" `
      "--update-secrets=$secrets" `
      "--update-labels=$labels" `
      "--quiet"
  }
  finally {
    Remove-Item -Recurse -Force $tmp, $zip -ErrorAction SilentlyContinue
  }

  $url = Get-GCloudOutput run services describe $script:StagingService @StagingArgs "--region=$script:Region" "--format=value(status.url)"
  $revision = Get-ServingRevisionName -Service $script:StagingService -GcloudArgs $StagingArgs
  $image = ""
  if ($revision) {
    $image = Get-GCloudOutput run revisions describe $revision @StagingArgs "--region=$script:Region" "--format=value(spec.containers[0].image)"
  }
  $deployedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  if (-not $url) { throw "Deploy finished but the service URL could not be read." }
  if (-not $revision) { throw "Deploy finished but the serving revision could not be read." }

  function Write-StagingReleaseRecord([bool]$SmokeOk) {
    $releasesDir = Join-Path $repoRoot "whatsapp-hello-bot\data\releases"
    New-Item -ItemType Directory -Path $releasesDir -Force | Out-Null
    $record = [ordered]@{
      git_sha     = $sha
      branch      = $branch
      revision    = $revision
      image       = $image
      url         = $url
      deployed_at = $deployedAt
      smoke_ok    = [bool]$SmokeOk
      service     = $script:StagingService
      project     = $script:StagingProject
      region      = $script:Region
    }
    $json = ($record | ConvertTo-Json -Depth 4)
    $outPath = Join-Path $releasesDir "staging-latest.json"
    $json | Set-Content -Path $outPath -Encoding utf8
    Write-Host "  record   : $outPath"

    $gcsLatest = "gs://$($script:StagingBucket)/releases/staging-latest.json"
    $tmpRec = Join-Path ([IO.Path]::GetTempPath()) ("staging-latest-" + [guid]::NewGuid().ToString("N").Substring(0, 8) + ".json")
    try {
      $json | Set-Content -Path $tmpRec -Encoding utf8
      Invoke-GCloud storage cp $tmpRec $gcsLatest @StagingArgs
      Write-Host "  record   : $gcsLatest"
      $hist = "gs://$($script:StagingBucket)/releases/history/$shortSha-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss')).json"
      Invoke-GCloud storage cp $tmpRec $hist @StagingArgs
    }
    finally {
      Remove-Item -Force $tmpRec -ErrorAction SilentlyContinue
    }
  }

  Write-Host ""
  Write-Host "Deployed." -ForegroundColor Green
  Write-Host "  commit   : $sha ($branch)"
  Write-Host "  serving  : $revision  (traffic-selected)"
  Write-Host "  image    : $image"
  Write-Host "  when     : $deployedAt"
  Write-Host "  url      : $url"
  Write-Host "  test chat: $url/admin/test-chat"

  if ($SkipSmokeTests) {
    Write-StagingReleaseRecord $false
    return
  }

  # ---- smoke tests ---------------------------------------------------------------
  Add-Type -AssemblyName System.Net.Http
  $handler = New-Object System.Net.Http.HttpClientHandler
  $handler.AllowAutoRedirect = $false
  $handler.UseCookies = $true
  $http = New-Object System.Net.Http.HttpClient($handler)
  $http.Timeout = [TimeSpan]::FromSeconds(60)

  $script:failures = @()
  function Check($name, $ok, $detail) {
    if ($ok) { Write-Host "  PASS  $name" -ForegroundColor Green }
    else { Write-Host "  FAIL  $name  ($detail)" -ForegroundColor Red; $script:failures += $name }
  }
  function Get-Url($path) { return $http.GetAsync("$url$path").GetAwaiter().GetResult() }

  Write-Host ""
  Write-Host "Smoke tests" -ForegroundColor Cyan

  $r = Get-Url "/health"
  Check "/health is 200" ($r.StatusCode -eq 200) $r.StatusCode

  $r = Get-Url "/webhook?hub.mode=subscribe&hub.verify_token=x&hub.challenge=1"
  Check "WhatsApp webhook is disabled (404)" ([int]$r.StatusCode -eq 404) $r.StatusCode

  $r = Get-Url "/docs"
  Check "API docs are disabled (404)" ([int]$r.StatusCode -eq 404) $r.StatusCode

  $r = Get-Url "/admin/test-chat"
  Check "Test Chat requires login (redirect)" ([int]$r.StatusCode -in 302, 303, 307) $r.StatusCode

  $r = Get-Url "/admin/test-chat/api/personas"
  Check "Test Chat JSON endpoint rejects anonymous (401)" ([int]$r.StatusCode -eq 401) $r.StatusCode

  $r = Get-Url "/admin"
  $body = $r.Content.ReadAsStringAsync().GetAwaiter().GetResult()
  Check "Admin page shows the STAGING banner" ($body -match "STAGING") "banner text not found"

  $r = Get-Url "/metrics"
  Check "/metrics requires login" ([int]$r.StatusCode -in 302, 303, 307, 401) $r.StatusCode

  if ($env:STAGING_ADMIN_PASSWORD) {
    $pairs = New-Object 'System.Collections.Generic.Dictionary[string,string]'
    $pairs.Add("password", $env:STAGING_ADMIN_PASSWORD)
    $form = New-Object System.Net.Http.FormUrlEncodedContent($pairs)
    $login = $http.PostAsync("$url/admin/login", $form).GetAwaiter().GetResult()
    Check "Admin login works with the staging password" ([int]$login.StatusCode -in 302, 303) $login.StatusCode
    $payload = New-Object System.Net.Http.StringContent('{"persona":"parent_a","text":"hello"}', [Text.Encoding]::UTF8, "application/json")
    $chat = $http.PostAsync("$url/admin/test-chat/api/message", $payload).GetAwaiter().GetResult()
    $chatBody = $chat.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    Check "Test Chat answers a message (200)" ($chat.StatusCode -eq 200 -and $chatBody -match '"messages"') "status=$($chat.StatusCode) body=$($chatBody.Substring(0, [Math]::Min(120, $chatBody.Length)))"
  }
  else {
    Write-Host "  (skipped authenticated checks: set `$env:STAGING_ADMIN_PASSWORD to include them)" -ForegroundColor DarkGray
  }

  if ($script:failures.Count -gt 0) {
    Write-StagingReleaseRecord $false
    throw "Smoke tests failed: $($script:failures -join '; ')"
  }
  Write-StagingReleaseRecord $true
  Write-Host ""
  Write-Host "All smoke tests passed." -ForegroundColor Green
}
finally {
  Pop-Location
}
