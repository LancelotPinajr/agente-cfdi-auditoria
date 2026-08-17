$PROJECT_ID = "project-d0428141-1b39-47af-9bc"
$REGION = "us-central1"
$SERVICE_NAME = "agente-cfdi-run"

# El SDK es una instalacion portatil y no esta en el PATH del sistema; y en esta
# maquina hay dos cuentas autenticadas, asi que fijamos la config explicitamente
# en vez de confiar en la que este activa.
$SDK_BIN = "D:\CORD\tools\google-cloud-sdk\bin"
if (Test-Path $SDK_BIN) { $env:Path = "$env:Path;$SDK_BIN" }
if (-not $env:CLOUDSDK_CONFIG) { $env:CLOUDSDK_CONFIG = "D:\CORD\tools\gcloud-config-ricardo" }

if ($null -eq (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "No se encontro gcloud. Se busco en: $SDK_BIN" -ForegroundColor Red
    exit 1
}

$ACCOUNT = gcloud config get-value account 2>$null
Write-Host "============================================="
Write-Host " Desplegando Agente CFDI a Cloud Run..."
Write-Host " Cuenta: $ACCOUNT"
Write-Host " Proyecto: $PROJECT_ID"
Write-Host "============================================="

# Habilitar Artifact Registry si no está habilitado (ya se habilitó en el Sprint 1, pero es buena práctica)
# gcloud services enable artifactregistry.googleapis.com

# Deploy usando source (Cloud Build compila el Dockerfile automáticamente)
gcloud run deploy $SERVICE_NAME `
    --source . `
    --project $PROJECT_ID `
    --region $REGION `
    --allow-unauthenticated `
    --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_REGION=global,GOOGLE_GENAI_USE_VERTEXAI=1"

if ($?) {
    Write-Host "`n✅ ¡Despliegue exitoso!"
    $URL = gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --project $PROJECT_ID --format="value(status.url)"
    Write-Host "🌍 La URL pública de tu agente es: $URL"
} else {
    Write-Host "`n❌ Error en el despliegue."
    Write-Host "Si el error menciona 'storage.objects.get' o un 403 sobre run-sources-*,"
    Write-Host "falta darle a la cuenta de build el rol builder (una sola vez):"
    Write-Host "  gcloud projects add-iam-policy-binding $PROJECT_ID ``"
    Write-Host "    --member=serviceAccount:1031368580327-compute@developer.gserviceaccount.com ``"
    Write-Host "    --role=roles/cloudbuild.builds.builder"
}
