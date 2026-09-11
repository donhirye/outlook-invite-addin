# Setup durable FAQ storage in GCS for Cloud Run.
# Run from PowerShell (as yourself, with gcloud logged in).
#
# BEFORE RUNNING: open /admin/faq, copy the full FAQ text, and save it to:
#   whatsapp-hello-bot\data\faq_backup.txt
# Otherwise a redeploy can replace your live FAQ with the sample file.

param(
  [string]$ProjectId = "",
  [string]$Region = "us-central1",
  [string]$ServiceName = "whatsapp-faq-bot",
  [string]$BucketName = "",
  [string]$FaqObject = "science_olympiad_faq.txt",
  [string]$IndexObject = "science_olympiad_faq.txt.index.json",
  [string]$LocalFaqPath = "",
  [switch]$Deploy
)

$ErrorActionPreference = "Stop"

if (-not $ProjectId) {
  $ProjectId = (gcloud config get-value project 2>$null).Trim()
}
if (-not $ProjectId) {
  throw "Set -ProjectId or run: gcloud config set project YOUR_PROJECT_ID"
}

if (-not $BucketName) {
  $BucketName = "$ProjectId-whatsapp-faq"
}

if (-not $LocalFaqPath) {
  $LocalFaqPath = Join-Path $PSScriptRoot "..\data\faq_backup.txt"
}

Write-Host "Project : $ProjectId"
Write-Host "Bucket  : gs://$BucketName"
Write-Host "Service : $ServiceName ($Region)"
Write-Host "FAQ file: $LocalFaqPath"
Write-Host ""

gcloud config set project $ProjectId | Out-Null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com --quiet

# Create bucket if missing
$bucketCheck = gcloud storage buckets describe "gs://$BucketName" 2>$null
if (-not $bucketCheck) {
  Write-Host "Creating bucket gs://$BucketName ..."
  gcloud storage buckets create "gs://$BucketName" --location=$Region --uniform-bucket-level-access
} else {
  Write-Host "Bucket already exists."
}

# Grant Cloud Run default compute SA object admin
$ProjectNumber = (gcloud projects describe $ProjectId --format="value(projectNumber)").Trim()
$ServiceAccount = "$ProjectNumber-compute@developer.gserviceaccount.com"
Write-Host "Granting roles/storage.objectAdmin to $ServiceAccount ..."
gcloud storage buckets add-iam-policy-binding "gs://$BucketName" `
  --member="serviceAccount:$ServiceAccount" `
  --role="roles/storage.objectAdmin" | Out-Null

# Upload FAQ backup if present (keeps your current content across the cutover)
if (Test-Path $LocalFaqPath) {
  Write-Host "Uploading FAQ from $LocalFaqPath ..."
  gcloud storage cp $LocalFaqPath "gs://$BucketName/$FaqObject"
} else {
  Write-Host ""
  Write-Host "WARNING: $LocalFaqPath not found."
  Write-Host "Copy your live FAQ from /admin/faq into that file, then re-run this script,"
  Write-Host "OR after deploy paste it back into /admin/faq and Save (writes to GCS)."
  Write-Host ""
}

$envVars = "FAQ_GCS_BUCKET=$BucketName,FAQ_GCS_OBJECT=$FaqObject,FAQ_GCS_INDEX_OBJECT=$IndexObject,FAQ_SKIP_RAG_MAX_CHARS=12000,OPENAI_MODEL=gpt-4o-mini"

if ($Deploy) {
  Write-Host "Deploying $ServiceName with durable FAQ env vars ..."
  Set-Location (Join-Path $PSScriptRoot "..")
  gcloud run deploy $ServiceName `
    --source . `
    --region $Region `
    --allow-unauthenticated `
    --min-instances 1 `
    --cpu-boost `
    --update-env-vars $envVars
} else {
  Write-Host ""
  Write-Host "Bucket + IAM are ready. Next, either:"
  Write-Host "  1) Re-run with -Deploy"
  Write-Host "  2) Or run:"
  Write-Host "     gcloud run deploy $ServiceName --source . --region $Region --allow-unauthenticated --min-instances 1 --cpu-boost --update-env-vars `"$envVars`""
}

Write-Host ""
Write-Host "After deploy, confirm / shows:"
Write-Host "  FAQ storage: gs://$BucketName/$FaqObject"
