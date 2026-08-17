# Configuración del proyecto
$PROJECT_ID = "project-d0428141-1b39-47af-9bc"
$REGION = "us-central1"
$CLOUD_RUN_URL = "https://agente-cfdi-run.a.run.app/api/cierre-diario" # URL temporal

Write-Host "============================================="
Write-Host " Sprint 2 - Configuración de Infraestructura"
Write-Host "============================================="

# 1. Secret Manager (Wallet)
Write-Host "`n[1/3] Configurando Secret Manager para la Wallet..."
$SECRET_NAME = "WALLET_PRIVATE_KEY"

$secretExists = gcloud secrets describe $SECRET_NAME --project=$PROJECT_ID 2>$null
if (-not $secretExists) {
    gcloud secrets create $SECRET_NAME --replication-policy="automatic" --project=$PROJECT_ID
    Write-Host "✅ Secreto $SECRET_NAME creado (vacío)."
    Write-Host "⚠️ IMPORTANTE: Sube tu llave ejecutando:"
    Write-Host "   gcloud secrets versions add $SECRET_NAME --data-file=tu_llave.txt --project=$PROJECT_ID"
} else {
    Write-Host "✅ El secreto $SECRET_NAME ya existe."
}

# 2. Cloud Scheduler (Job Diario con Reintentos)
Write-Host "`n[2/3] Configurando Cloud Scheduler..."
$JOB_NAME = "job-cierre-diario"

# Reintentos max 3
gcloud scheduler jobs create http $JOB_NAME `
    --schedule="59 23 * * *" `
    --time-zone="America/Mexico_City" `
    --uri=$CLOUD_RUN_URL `
    --http-method=POST `
    --max-retry-attempts=3 `
    --min-backoff=10s `
    --max-backoff=300s `
    --max-retry-duration=10m `
    --project=$PROJECT_ID `
    --location=$REGION

if ($?) {
    Write-Host "✅ Job de Scheduler '$JOB_NAME' creado exitosamente."
}

# 3. Monitoreo y Alertas
Write-Host "`n[3/3] Configurando Alertas de Logs..."
Write-Host "Para completar 2.11 (Logs y alertas):"
Write-Host "1. Entra a GCP -> Monitoring -> Alerting"
Write-Host "2. Crea una política basada en este filtro:"
Write-Host "   resource.type=`"cloud_scheduler_job`" AND severity>=ERROR"
Write-Host "============================================="
Write-Host "¡Script finalizado!"
