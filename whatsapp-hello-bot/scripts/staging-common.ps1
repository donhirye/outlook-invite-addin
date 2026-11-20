# Shared constants and safety guards for the STAGING scripts.
# Dot-source this file:  . "$PSScriptRoot\staging-common.ps1"
#
# Design rules (see docs/staging.md):
#   * Every gcloud call names the staging project explicitly. We never read or change
#     the "default project" from `gcloud config`.
#   * Staging calls impersonate a staging-only service account, so even if this script
#     were edited by mistake, the credentials it uses cannot touch production.
#   * There is deliberately no switch, parameter or environment variable that points
#     these scripts at production.

$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
  $PSNativeCommandUseErrorActionPreference = $false
}

$script:ProdProject    = "vi1234"
$script:ProdService    = "whatsapp-faq-bot"
$script:ProdBucket     = "vi1234-whatsapp-faq"

$script:StagingProject = "vi1234-staging"
$script:Region         = "us-central1"
$script:StagingService = "whatsapp-faq-bot-staging"
$script:StagingBucket  = "vi1234-staging-whatsapp-faq"
$script:DeployerSaName = "staging-deployer"
$script:RuntimeSaName  = "staging-runtime"
$script:DeployerSa     = "$($script:DeployerSaName)@$($script:StagingProject).iam.gserviceaccount.com"
$script:RuntimeSa      = "$($script:RuntimeSaName)@$($script:StagingProject).iam.gserviceaccount.com"

# Secret Manager secret names (values never touch Git or this repo).
$script:SecretAdminPassword = "staging-admin-password"
$script:SecretSecretKey     = "staging-secret-key"
$script:SecretOpenAiKey     = "staging-openai-api-key"

# Fake test-persona phone for the FAQ-admin persona (never a real parent number).
$script:StagingAdminPhones = "15550100003"

function Assert-StagingTarget {
  # Belt and braces: refuse to run if any target constant was edited to look like prod.
  foreach ($pair in @(
      @("project", $script:StagingProject),
      @("service", $script:StagingService),
      @("bucket", $script:StagingBucket),
      @("deployer", $script:DeployerSa),
      @("runtime", $script:RuntimeSa))) {
    $name, $value = $pair
    if ($value -notmatch "staging") {
      throw "Refusing to continue: staging $name '$value' does not contain 'staging'."
    }
  }
  if ($script:StagingProject -eq $script:ProdProject) {
    throw "Refusing to continue: staging project equals the production project."
  }
  if ($script:StagingService -eq $script:ProdService) {
    throw "Refusing to continue: staging service equals the production service."
  }
  if ($script:StagingBucket -eq $script:ProdBucket) {
    throw "Refusing to continue: staging bucket equals the production bucket."
  }
}

function Assert-AllowedStagingBranch {
  # Allow feature/* and experiment/* (and main) onto staging. Block laptop-only / WIP names.
  # Hard anti-prod checks remain in Assert-StagingTarget / Invoke-GCloud.
  param([Parameter(Mandatory = $true)][string]$Branch)
  if ($Branch -eq 'main' -or $Branch -eq 'master') { return }
  if ($Branch -match '^(feature|experiment)/') { return }
  if ($Branch -match '^(dev|local|wip|scratch)/' -or
      $Branch -match '(^|/)(local-dev|dev-worktree|local-scratch)(/|$)' -or
      $Branch -eq 'feature/local-dev-environment' -or
      $Branch -eq 'experiment/local-scratch') {
    throw ("Refusing to deploy laptop-only / WIP branch '{0}'. " +
           "Use feature/<name> or experiment/<name>, or restore from main.") -f $Branch
  }
  throw ("Refusing to deploy branch '{0}'. Staging deploys allow main, feature/*, or experiment/* only.") -f $Branch
}

# Backward-compatible alias (older scripts / docs).
function Assert-NotExperimentalBranch {
  param([Parameter(Mandatory = $true)][string]$Branch)
  Assert-AllowedStagingBranch -Branch $Branch
}

function Get-BranchFaqPrefix {
  # Baseline objects have no prefix. Experiment branches get experiments/<slug>/.
  param([Parameter(Mandatory = $true)][string]$Branch)
  if ($Branch -eq 'main' -or $Branch -eq 'master') { return "" }
  $slug = ($Branch -replace '[^a-zA-Z0-9._-]', '-').ToLowerInvariant()
  if ($slug.Length -gt 80) { $slug = $slug.Substring(0, 80) }
  return "experiments/$slug"
}

function Assert-NotProductionTarget {
  param(
    [string]$Project = $script:StagingProject,
    [string]$Service = $script:StagingService
  )
  if ($Project -eq $script:ProdProject -or $Service -eq $script:ProdService) {
    throw "Refusing: staging scripts must never target production project/service."
  }
  if ($Project -notmatch 'staging' -or $Service -notmatch 'staging') {
    throw "Refusing: target project/service must contain 'staging'."
  }
}

function Invoke-GCloud {
  # Runs gcloud and throws on failure. Callers must pass --project explicitly.
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GcloudArgs)
  if ($GcloudArgs -contains "--project=$($script:ProdProject)" -or
      ($GcloudArgs -join " ") -match "--project[ =]$([regex]::Escape($script:ProdProject))(\s|$)") {
    throw "Refusing: staging scripts must not target project '$($script:ProdProject)'."
  }
  $ErrorActionPreference = "Continue"
  & gcloud @GcloudArgs
  if ($LASTEXITCODE -ne 0) {
    throw "gcloud failed ($LASTEXITCODE): gcloud $($GcloudArgs -join ' ')"
  }
}

function Get-GCloudOutput {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GcloudArgs)
  $ErrorActionPreference = "Continue"
  $out = & gcloud @GcloudArgs 2>$null
  if ($LASTEXITCODE -ne 0) { return "" }
  return (($out | Out-String).Trim())
}

# Common arguments for staging commands that should run as the deployer service account.
function Get-StagingArgs {
  return @(
    "--project=$($script:StagingProject)",
    "--impersonate-service-account=$($script:DeployerSa)"
  )
}

# Splat this (@StagingArgs) after dot-sourcing: it must stay a real array, not a joined string.
$StagingArgs = Get-StagingArgs
