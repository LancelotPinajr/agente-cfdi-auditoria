$PROJECT_ID = "project-d0428141-1b39-47af-9bc"
$REGION = "us-central1"
$SERVICE_NAME = "agente-cfdi-run"

Write-Host "============================================="
Write-Host " Desplegando Agente CFDI a Cloud Run..."
Write-Host "============================================="

# Habilitar Artifact Registry si no está habilitado (ya se habilitó en el Sprint 1, pero es buena práctica)
# gcloud services enable artifactregistry.googleapis.com

# Deploy usando source (Cloud Build compila el Dockerfile automáticamente)
gcloud run deploy $SERVICE_NAME `
    --source . `
    --project $PROJECT_ID `
    --region $REGION `
    --allow-unauthenticated `
    --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_REGION=global"

if ($?) {
    Write-Host "`n✅ ¡Despliegue exitoso!"
    $URL = gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --project $PROJECT_ID --format="value(status.url)"
    Write-Host "🌍 La URL pública de tu agente es: $URL"
} else {
    Write-Host "`n❌ Error en el despliegue."
}
