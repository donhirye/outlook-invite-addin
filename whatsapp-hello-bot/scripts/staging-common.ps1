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

function Assert-NotExperimentalBranch {
  # Local DEV / scratch branches must never be pushed through staging deploy scripts.
  param([Parameter(Mandatory = $true)][string]$Branch)
  if ($Branch -match '^(dev|local|experiment|wip|scratch)/' -or
      $Branch -match '(^|/)(local-dev|dev-worktree|experiment)(/|$)' -or
      $Branch -eq 'feature/local-dev-environment') {
    throw ("Refusing to deploy experimental/local-dev branch '{0}'. " +
           "Promote changes via PR to main (or an approved release branch) first.") -f $Branch
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
