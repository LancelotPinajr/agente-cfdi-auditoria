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
# --- Anclaje en cadena real (tareas 2.7 y 3.6) -----------------------------
#
# Estas TRES van aqui y no se configuran aparte con `gcloud run services update`,
# aunque asi se pusieron la primera vez. La razon es `--set-env-vars` de abajo:
# REEMPLAZA la lista completa de variables, no la actualiza. Cualquier variable
# fijada fuera de este script desaparece en el siguiente despliegue.
#
# Paso el 21-ago-2026: el ancla real quedo configurada, un despliegue posterior
# la borro sin avisar, y esa noche el cierre corrio bien y anclo con la SIMULADA.
# El job devolvio 200, el tablero verde, y la unica pista era `red:
# simulada:local` en el log del cierre.
#
# Los secretos (--update-secrets) van en otra lista y por eso el token de
# escritura si sobrevivio a aquel despliegue. Las variables no.
$ANCLA_RED = "base-sepolia"
$ANCLA_CONTRATO = "0xe76b981159307a79c77B29796F59087D6c13d974"
$LLAVE_SECRETO = "WALLET_PRIVATE_KEY"

# --- Respaldo de la bitacora (tareas 3.13 y 3.14) --------------------------
#
# La cubeta tiene que existir ANTES del primer despliegue que use esta
# variable. Se crea una sola vez con ./configurar_respaldo.ps1, que ademas le
# activa el versionado y le da permiso a la cuenta de servicio.
#
# Si la cubeta no existe el servicio NO se cae: arranca, escribe en local y
# reporta `degradado` en /semaforo con el error de GCS. Eso es deliberado
# —perder la copia no debe tumbar el servicio— pero significa que el fallo se
# ve en el semaforo y no en el despliegue. Revisalo despues de desplegar.
$CUBETA_RESPALDO = "$PROJECT_ID-bitacora"

Write-Host "============================================="
Write-Host " Desplegando Agente CFDI a Cloud Run..."
Write-Host " Cuenta: $ACCOUNT"
Write-Host " Proyecto: $PROJECT_ID"
Write-Host "============================================="

# Habilitar Artifact Registry si no está habilitado (ya se habilitó en el Sprint 1, pero es buena práctica)
# gcloud services enable artifactregistry.googleapis.com

# Deploy usando source (Cloud Build compila el Dockerfile automáticamente)
# --max-instances=1 NO es una optimizacion de costo: es una CONDICION DE
# CORRECCION. Ver docs/adr/0007-dominio-del-candado-y-dominio-de-la-durabilidad.md
#
# La bitacora es SQLite sobre el disco efimero de la instancia
# (src/agente_cfdi/api/dependencias.py). Con dos instancias vivas cada una
# escribiria contra su propio archivo y la punta se bifurcaria EN SILENCIO:
# ninguna de las dos daria error, las dos verificarian, y al cierre se anclaria
# una raiz que solo cubre la mitad de los registros. Es el peor fallo que puede
# tener este producto: uno que produce evidencia de aspecto correcto.
#
# NO SUBAS ESTE NUMERO sin leer el ADR 0007 primero. El dia que la bitacora
# corra sobre PostgreSQL, pg_advisory_xact_lock es por inquilino y este
# invariante deja de ser necesario. Hoy no.
#
# AGENTE_CFDI_BITACORA apunta a /tmp porque es el unico lugar que Cloud Run
# garantiza escribible. /tmp SIGUE perdiendose al reciclar la instancia: lo que
# cambio con 3.13 y 3.14 es que ya no importa, porque AGENTE_CFDI_RESPALDO
# replica el archivo a GCS tras cada confirmacion y el arranque lo restaura.
#
# Lo que NO resuelve: la ventana entre una confirmacion y su subida. Un SIGKILL
# ahi se lleva esas escrituras. Esta acotada a una subida y esta declarada en
# src/agente_cfdi/bitacora/respaldo.py; /semaforo la reporta en `respaldo`.
#
# AGENTE_CFDI_SEMILLA tiene que coincidir con la que usa tools/demo.py. Si no,
# los libros sinteticos y los CFDI hablan de empresas distintas y TODO sale
# sin_respaldo — pareceria que el auditor falla cuando en realidad se le esta
# preguntando por facturas que nunca vio.
#
# --min-instances=1 mantiene la instancia viva entre un cierre y el siguiente.
# Se puso como PUENTE mientras /tmp era el unico sitio donde vivia la cadena:
# sin esto Cloud Run reciclaba la instancia sin trafico, /tmp se borraba, y el
# cierre de manana arrancaba en altura 0.
#
# Con 3.13 y 3.14 ese puente ya no carga peso: la cadena se restaura del
# snapshot al arrancar, asi que un reciclaje deja de ser una perdida. Se
# mantiene en 1 a proposito hasta que 3.17 lo demuestre contra el servicio real
# —quitar la red antes de comprobar que el suelo aguanta es como se pierde una
# demo— y en cuanto esa evidencia exista, esto puede bajar a 0 y ahorrarse una
# instancia encendida todo el mes.
gcloud run deploy $SERVICE_NAME `
    --source . `
    --project $PROJECT_ID `
    --region $REGION `
    --allow-unauthenticated `
    --max-instances=1 `
    --min-instances=1 `
    --set-env-vars="GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_REGION=global,GOOGLE_GENAI_USE_VERTEXAI=1,AGENTE_CFDI_BITACORA=/tmp/bitacora.db,AGENTE_CFDI_SEMILLA=20260814,AGENTE_CFDI_ANCLA_RED=$ANCLA_RED,AGENTE_CFDI_ANCLA_CONTRATO=$ANCLA_CONTRATO,AGENTE_CFDI_LLAVE_SECRETO=$LLAVE_SECRETO,AGENTE_CFDI_RESPALDO=gs://$CUBETA_RESPALDO/bitacora/bitacora.db"

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
