# Cierra las escrituras del servicio publico (punto 3 del plan de cierre).
#
# ## Que hace y por que en este orden
#
# El servicio esta abierto a proposito para que un jurado pueda probarlo sin
# credenciales. Lo que no puede seguir abierto es la ESCRITURA: desde que el
# motor de auditoria se monto, cualquiera con la URL podia ingerir CFDI,
# registrar cesiones y disparar el cierre del dia.
#
#   1. Genera un token y lo guarda en Secret Manager.
#   2. Le da a la cuenta de servicio permiso de leerlo.
#   3. Se lo inyecta a Cloud Run como variable de entorno.
#   4. Se lo pone al scheduler en la cabecera Authorization.
#
# El paso 4 no es opcional: en cuanto el paso 3 surte efecto, el job diario
# empieza a recibir 401 y el cierre deja de correr. Los dos van juntos o el
# sistema queda peor que antes.
#
# ## Sobre la rotacion
#
# Este token SI exige redesplegar para rotarse, a diferencia de la llave de la
# wallet. Es deliberado: la llave firma dinero y su criterio (2.10) pedia
# rotacion en caliente; este token solo controla quien escribe en una bitacora
# de demo, y mantenerlo como variable de entorno lo hace legible en el panel de
# Cloud Run, que es justo lo que hace falta para depurar un 403.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File ./configurar_escritura.ps1

$PROJECT_ID = "project-d0428141-1b39-47af-9bc"
$REGION = "us-central1"
$SERVICIO = "agente-cfdi-run"
$JOB = "job-cierre-diario"
$SECRETO = "agente-cfdi-token-escritura"
$CUENTA = "1031368580327-compute@developer.gserviceaccount.com"

$SDK_BIN = "D:\CORD\tools\google-cloud-sdk\bin"
if (Test-Path $SDK_BIN) { $env:Path = "$env:Path;$SDK_BIN" }
if (-not $env:CLOUDSDK_CONFIG) { $env:CLOUDSDK_CONFIG = "D:\CORD\tools\gcloud-config-ricardo" }

Write-Host "============================================="
Write-Host " Cerrando las escrituras del servicio"
Write-Host " Proyecto: $PROJECT_ID"
Write-Host "============================================="

# --- 1. El secreto ---------------------------------------------------------

Write-Host "`n[1/4] Token en Secret Manager..."

$existe = gcloud secrets describe $SECRETO --project=$PROJECT_ID 2>$null
if (-not $existe) {
    gcloud secrets create $SECRETO --replication-policy="automatic" --project=$PROJECT_ID | Out-Null
    Write-Host "   secreto creado: $SECRETO"
}

$versiones = gcloud secrets versions list $SECRETO --project=$PROJECT_ID --format="value(name)" 2>$null
if (-not $versiones) {
    # 32 bytes de entropia en base64url. El token viaja por una tuberia igual
    # que la llave de la wallet: no se escribe en disco ni pasa por argv.
    $token = & .\.venv\Scripts\python.exe -c "import secrets,sys; sys.stdout.write(secrets.token_urlsafe(32))"
    $token | & gcloud secrets versions add $SECRETO --data-file=- --project=$PROJECT_ID | Out-Null
    Write-Host "   token generado y guardado (no se muestra)"
} else {
    Write-Host "   el secreto ya tiene version; se reutiliza"
}

# --- 2. Permiso de lectura -------------------------------------------------

Write-Host "`n[2/4] Permiso para la cuenta de servicio..."
gcloud secrets add-iam-policy-binding $SECRETO `
    --member="serviceAccount:$CUENTA" `
    --role="roles/secretmanager.secretAccessor" `
    --project=$PROJECT_ID | Out-Null
if ($?) { Write-Host "   $CUENTA puede leer $SECRETO" }

# --- 3. Cloud Run ----------------------------------------------------------

Write-Host "`n[3/4] Inyectando el token en Cloud Run..."
gcloud run services update $SERVICIO `
    --region=$REGION `
    --project=$PROJECT_ID `
    --update-secrets="AGENTE_CFDI_TOKEN_ESCRITURA=${SECRETO}:latest"
if (-not $?) {
    Write-Host "`nNo se pudo actualizar el servicio. Se aborta ANTES de tocar el" -ForegroundColor Red
    Write-Host "scheduler: dejarlo con un token que el servicio no espera romperia" -ForegroundColor Red
    Write-Host "el cierre diario sin cerrar nada." -ForegroundColor Red
    exit 1
}

# --- 4. Scheduler ----------------------------------------------------------

Write-Host "`n[4/4] Dandole el token al job diario..."
$token = gcloud secrets versions access latest --secret=$SECRETO --project=$PROJECT_ID
gcloud scheduler jobs update http $JOB `
    --location=$REGION `
    --project=$PROJECT_ID `
    --update-headers="Authorization=Bearer $token"
if ($?) { Write-Host "   el job diario ya manda el token" }

Write-Host "`n============================================="
Write-Host " Listo. Comprobar que la puerta quedo puesta:"
Write-Host ""
Write-Host "   curl -s -o /dev/null -w '%{http_code}\n' \"
Write-Host "     -X POST https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria/cierre-diario"
Write-Host "   -> debe responder 401"
Write-Host ""
Write-Host "   curl -s https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/auditoria/semaforo"
Write-Host "   -> debe seguir respondiendo 200 sin credencial"
Write-Host "============================================="
