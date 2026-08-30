# Crea la cubeta donde se replica la bitacora (tareas 3.13 y 3.14).
#
# ## Que hace y por que en este orden
#
#   1. Crea la cubeta, si no existe.
#   2. Le activa el VERSIONADO.
#   3. Le pone una regla de ciclo de vida que poda las versiones viejas.
#   4. Le da a la cuenta de servicio de Cloud Run permiso de leer y escribir.
#
# El paso 3 va antes del 4 a proposito. El servicio sube una copia COMPLETA de
# la bitacora tras cada confirmacion, asi que con versionado y sin poda la
# cubeta acumula una version por cada CFDI ingerido. En una demo son unos pocos
# megabytes; en cuanto alguien corra un lote grande, no. Activar el versionado
# sin la regla de poda es una factura esperando a ocurrir, y se descubriria a
# fin de mes.
#
# ## Por que versionado, si el codigo solo lee la ultima
#
# Porque el modo de fallo que importa no es perder el archivo: es replicar un
# archivo malo encima del bueno. La restauracion revisa el snapshot con
# `PRAGMA integrity_check` y se niega a instalar uno corrupto (arranca vacia y
# lo dice), pero eso solo protege del corrupto EVIDENTE. El versionado es lo
# que permite volver a la copia de anteayer si hiciera falta.
#
# Uso, una sola vez:
#   powershell -ExecutionPolicy Bypass -File ./configurar_respaldo.ps1

$PROJECT_ID = "project-d0428141-1b39-47af-9bc"
$REGION = "us-central1"
$CUBETA = "$PROJECT_ID-bitacora"
$CUENTA_DE_SERVICIO = "1031368580327-compute@developer.gserviceaccount.com"

# Mismo arranque que deploy.ps1: el SDK es portatil y no esta en el PATH, y en
# esta maquina hay dos cuentas autenticadas.
$SDK_BIN = "D:\CORD\tools\google-cloud-sdk\bin"
if (Test-Path $SDK_BIN) { $env:Path = "$env:Path;$SDK_BIN" }
if (-not $env:CLOUDSDK_CONFIG) { $env:CLOUDSDK_CONFIG = "D:\CORD\tools\gcloud-config-ricardo" }

if ($null -eq (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "No se encontro gcloud. Se busco en: $SDK_BIN" -ForegroundColor Red
    exit 1
}

Write-Host "============================================="
Write-Host " Configurando el respaldo de la bitacora"
Write-Host " Cubeta: gs://$CUBETA"
Write-Host "============================================="

# --- 1. La cubeta ----------------------------------------------------------
# $LASTEXITCODE y no $?: tras redirigir la salida de un ejecutable nativo, $?
# deja de reflejar el codigo de salida real en PowerShell 5.1.
gcloud storage buckets describe "gs://$CUBETA" --project $PROJECT_ID > $null 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[1/4] La cubeta ya existe, no se toca."
} else {
    Write-Host "`n[1/4] Creando gs://$CUBETA ..."
    # --uniform-bucket-level-access: sin ACL por objeto. El permiso se da una
    # vez a nivel de cubeta (paso 4) y no hay forma de que un objeto quede
    # publico por accidente.
    gcloud storage buckets create "gs://$CUBETA" `
        --project $PROJECT_ID `
        --location $REGION `
        --uniform-bucket-level-access `
        --public-access-prevention
    if ($LASTEXITCODE -ne 0) {
        Write-Host "No se pudo crear la cubeta. Si el nombre ya lo tomo otro" -ForegroundColor Red
        Write-Host "proyecto, cambia `$CUBETA aqui Y en deploy.ps1: los dos" -ForegroundColor Red
        Write-Host "tienen que decir lo mismo o el servicio replicara a otro sitio." -ForegroundColor Red
        exit 1
    }
}

# --- 2. Versionado ---------------------------------------------------------
Write-Host "`n[2/4] Activando el versionado ..."
gcloud storage buckets update "gs://$CUBETA" --project $PROJECT_ID --versioning

# --- 3. Poda de versiones viejas -------------------------------------------
#
# Se conservan las 30 versiones no vigentes mas recientes, y ademas nada no
# vigente sobrevive mas de 14 dias. Las dos condiciones a la vez: la primera
# acota el pico de un lote grande, la segunda acota el goteo de una demo que
# corre sola todos los dias.
Write-Host "`n[3/4] Poniendo la regla de ciclo de vida ..."
$REGLA = @'
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {"isLive": false, "numNewerVersions": 30}
    },
    {
      "action": {"type": "Delete"},
      "condition": {"isLive": false, "daysSinceNoncurrentTime": 14}
    }
  ]
}
'@
$ARCHIVO_REGLA = Join-Path $env:TEMP "ciclo-de-vida-bitacora.json"
$REGLA | Out-File -FilePath $ARCHIVO_REGLA -Encoding utf8
gcloud storage buckets update "gs://$CUBETA" --project $PROJECT_ID --lifecycle-file=$ARCHIVO_REGLA
Remove-Item $ARCHIVO_REGLA -ErrorAction SilentlyContinue

# --- 4. Permiso para la cuenta de servicio ---------------------------------
#
# objectAdmin y no objectCreator: el servicio necesita LEER el snapshot al
# arrancar (3.13), no solo escribirlo. Con objectCreator la restauracion
# fallaria con un 403 y el sintoma seria una cadena que arranca vacia: el
# semaforo lo diria, pero cuesta mas de depurar que darlo bien de una vez.
Write-Host "`n[4/4] Dando permiso a $CUENTA_DE_SERVICIO ..."
gcloud storage buckets add-iam-policy-binding "gs://$CUBETA" `
    --project $PROJECT_ID `
    --member="serviceAccount:$CUENTA_DE_SERVICIO" `
    --role="roles/storage.objectAdmin"

if ($LASTEXITCODE -eq 0) {
    Write-Host "`nListo. Ahora ./deploy.ps1 ya puede usar AGENTE_CFDI_RESPALDO."
    Write-Host "Despues de desplegar, comprueba que NO diga degradado:"
    Write-Host "  curl -s <URL>/semaforo | python -m json.tool"
    Write-Host "El bloque `"respaldo`" tiene que traer restauracion y destino."
} else {
    Write-Host "`nFallo el permiso. Sin el, el servicio arranca igual pero" -ForegroundColor Red
    Write-Host "reporta degradado en /semaforo y la bitacora no se replica." -ForegroundColor Red
}
