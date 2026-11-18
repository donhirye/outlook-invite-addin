# One-time provisioning of the STAGING Google Cloud project.
#
#   .\scripts\provision-staging.ps1 -DryRun     # print every command, change nothing
#   .\scripts\provision-staging.ps1             # do it (asks to confirm first)
#
# Runs as YOU (project creation/billing need your own account). It creates only
# resources inside the new project vi1234-staging and links it to the billing account.
# It never touches the production project. Safe to re-run: existing resources are kept.
#
# After this, day-to-day deploys use scripts\deploy-staging.ps1 (deployer service account).
#
# Spending controls (read docs/staging.md):
#   * GCP budget alerts only EMAIL you - they do not stop anything.
#   * The real limits are: Cloud Run max-instances=2, and the OpenAI project spend limit
#     ($20 hard limit) that you set on the separate staging OpenAI project.

param(
  [string]$BillingAccount = "01C3FE-17A917-11B1FE",
  [decimal]$MonthlyBudgetUsd = 20,
  [switch]$DryRun,
  [switch]$Yes,
  [switch]$SetOpenAiKey   # prompt for the staging OpenAI key and store it in Secret Manager
)

. "$PSScriptRoot\staging-common.ps1"
Assert-StagingTarget

$P = $script:StagingProject

function Step($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Run {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GcloudArgs)
  if ($DryRun) { Write-Host "  [dry-run] gcloud $($GcloudArgs -join ' ')" -ForegroundColor DarkGray; return }
  Invoke-GCloud @GcloudArgs
}
function Exists {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GcloudArgs)
  if ($DryRun) { return $false }
  $ErrorActionPreference = "Continue"
  & gcloud @GcloudArgs 2>$null | Out-Null
  return ($LASTEXITCODE -eq 0)
}
function New-RandomToken([int]$bytes) {
  $buf = New-Object byte[] $bytes
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buf)
  return ([Convert]::ToBase64String($buf) -replace "[^A-Za-z0-9]", "")
}
function Set-SecretValue([string]$name, [string]$value) {
  # Temp file without a trailing newline; removed immediately.
  $f = Join-Path ([IO.Path]::GetTempPath()) ("sec-" + [guid]::NewGuid().ToString("N"))
  try {
    [IO.File]::WriteAllText($f, $value, (New-Object Text.UTF8Encoding($false)))
    Run secrets versions add $name "--project=$P" "--data-file=$f"
  }
  finally { Remove-Item -Force $f -ErrorAction SilentlyContinue }
}

$account = Get-GCloudOutput config get-value account
Write-Host "Staging provisioning" -ForegroundColor Cyan
Write-Host "  gcloud account : $account"
Write-Host "  new project    : $P"
Write-Host "  billing account: billingAccounts/$BillingAccount"
Write-Host "  monthly budget : `$$MonthlyBudgetUsd (alerts only)"
if ($DryRun) { Write-Host "  mode           : DRY RUN" -ForegroundColor Yellow }
if (-not $account) { throw "No gcloud account. Run: gcloud auth login" }
if (-not $DryRun -and -not $Yes) {
  $answer = Read-Host "Create/configure project '$P' under this account? (type 'yes')"
  if ($answer -ne "yes") { throw "Cancelled." }
}

Step "Project"
if (-not (Exists projects describe $P)) {
  Run projects create $P "--name=WhatsApp bot staging"
}
else { Write-Host "  exists: $P" }

Step "Billing link"
Run billing projects link $P "--billing-account=$BillingAccount"

Step "Enable APIs"
Run services enable "--project=$P" `
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com `
  secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com `
  iamcredentials.googleapis.com cloudresourcemanager.googleapis.com `
  serviceusage.googleapis.com logging.googleapis.com billingbudgets.googleapis.com

Step "Service accounts"
foreach ($n in @($script:DeployerSaName, $script:RuntimeSaName)) {
  $email = "$n@$P.iam.gserviceaccount.com"
  if (-not (Exists iam service-accounts describe $email "--project=$P")) {
    Run iam service-accounts create $n "--project=$P" "--display-name=$n"
  }
  else { Write-Host "  exists: $email" }
}

$projectNumber = if ($DryRun) { "<PROJECT_NUMBER>" } else { Get-GCloudOutput projects describe $P "--format=value(projectNumber)" }
$computeSa = "$projectNumber-compute@developer.gserviceaccount.com"

Step "Deployer permissions (staging project only)"
foreach ($role in @(
    "roles/run.admin", "roles/cloudbuild.builds.editor", "roles/artifactregistry.admin",
    "roles/storage.admin", "roles/serviceusage.serviceUsageConsumer", "roles/logging.viewer")) {
  Run projects add-iam-policy-binding $P "--member=serviceAccount:$script:DeployerSa" "--role=$role" "--condition=None" "--quiet" | Out-Null
}
# Cloud Build in a new project runs as the default compute service account.
Run projects add-iam-policy-binding $P "--member=serviceAccount:$computeSa" "--role=roles/cloudbuild.builds.builder" "--condition=None" "--quiet" | Out-Null
foreach ($sa in @($script:RuntimeSa, $computeSa)) {
  Run iam service-accounts add-iam-policy-binding $sa "--project=$P" "--member=serviceAccount:$script:DeployerSa" "--role=roles/iam.serviceAccountUser" "--quiet" | Out-Null
}

Step "Let you impersonate the deployer"
Run iam service-accounts add-iam-policy-binding $script:DeployerSa "--project=$P" "--member=user:$account" "--role=roles/iam.serviceAccountTokenCreator" "--quiet" | Out-Null

Step "Storage bucket (data for staging only)"
if (-not (Exists storage buckets describe "gs://$script:StagingBucket" "--project=$P")) {
  Run storage buckets create "gs://$script:StagingBucket" "--project=$P" "--location=$script:Region" "--uniform-bucket-level-access" "--public-access-prevention"
}
else { Write-Host "  exists: gs://$script:StagingBucket" }
Run storage buckets add-iam-policy-binding "gs://$script:StagingBucket" "--project=$P" "--member=serviceAccount:$script:RuntimeSa" "--role=roles/storage.objectAdmin" | Out-Null
Run storage buckets add-iam-policy-binding "gs://$script:StagingBucket" "--project=$P" "--member=serviceAccount:$script:DeployerSa" "--role=roles/storage.objectAdmin" | Out-Null

Step "Secrets"
$newAdminPassword = $null
foreach ($s in @($script:SecretAdminPassword, $script:SecretSecretKey, $script:SecretOpenAiKey)) {
  if (-not (Exists secrets describe $s "--project=$P")) {
    Run secrets create $s "--project=$P" "--replication-policy=automatic"
  }
  Run secrets add-iam-policy-binding $s "--project=$P" "--member=serviceAccount:$script:RuntimeSa" "--role=roles/secretmanager.secretAccessor" | Out-Null
}
if (-not $DryRun) {
  $hasPw = Get-GCloudOutput secrets versions list $script:SecretAdminPassword "--project=$P" "--limit=1" "--format=value(name)"
  if (-not $hasPw) {
    $newAdminPassword = New-RandomToken 24
    Set-SecretValue $script:SecretAdminPassword $newAdminPassword
    Set-SecretValue $script:SecretSecretKey (New-RandomToken 48)
  }
  else { Write-Host "  admin password / secret key already set (not changed)" }
}
if ($SetOpenAiKey) {
  # Prefer an env var so PowerShell's SecureString decode quirks don't reject a valid key.
  # Usage:  $env:STAGING_OPENAI_API_KEY = "sk-..."; .\scripts\provision-staging.ps1 -SetOpenAiKey
  $plain = $env:STAGING_OPENAI_API_KEY
  if (-not $plain) {
    $sec = Read-Host "Paste the STAGING OpenAI API key (input hidden)" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    try {
      # PtrToStringBSTR (not Auto) — Auto can return empty/garbage on PowerShell 7.
      $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
      [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
    }
  }
  $plain = if ($null -eq $plain) { "" } else { $plain.Trim() }
  if ($plain -notmatch '^sk-[A-Za-z0-9_\-]+$') {
    $prefix = if ($plain.Length -ge 3) { $plain.Substring(0, 3) } else { "(empty)" }
    throw "That does not look like an OpenAI key (got length $($plain.Length), starts with '$prefix'). Expected sk-... Re-run, or set `$env:STAGING_OPENAI_API_KEY first."
  }
  Set-SecretValue $script:SecretOpenAiKey $plain
  $plain = $null
  Remove-Item Env:STAGING_OPENAI_API_KEY -ErrorAction SilentlyContinue
  Write-Host "  OpenAI key stored in Secret Manager ($($script:SecretOpenAiKey))." -ForegroundColor Green
}
else {
  Write-Host "  OpenAI key not set. Re-run with -SetOpenAiKey once you have created the staging key." -ForegroundColor Yellow
}

Step "Budget alerts (email only - NOT a spending limit)"
if ($DryRun -or -not (Get-GCloudOutput billing budgets list "--billing-account=$BillingAccount" "--billing-project=$P" "--filter=displayName:'$P monthly alert'" "--format=value(name)")) {
  Run billing budgets create "--billing-account=$BillingAccount" "--billing-project=$P" "--display-name=$P monthly alert" `
    "--budget-amount=${MonthlyBudgetUsd}USD" "--filter-projects=projects/$projectNumber" `
    "--threshold-rule=percent=0.5" "--threshold-rule=percent=0.8" "--threshold-rule=percent=1.0"
}
else { Write-Host "  budget already exists" }

Write-Host ""
Write-Host "Provisioning complete." -ForegroundColor Green
if ($newAdminPassword) {
  Write-Host ""
  Write-Host "STAGING ADMIN PASSWORD (shown once; stored in Secret Manager '$($script:SecretAdminPassword)'):" -ForegroundColor Yellow
  Write-Host "  $newAdminPassword"
  Write-Host "Put it in a password manager. To read it later:"
  Write-Host "  gcloud secrets versions access latest --secret=$($script:SecretAdminPassword) --project=$P"
}
Write-Host ""
Write-Host "Next: seed reference data (scripts\seed-staging-data.ps1), then scripts\deploy-staging.ps1"
