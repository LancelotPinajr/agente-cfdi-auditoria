# Alertas del cierre diario (tarea 2.11).
#
# La version anterior de esto era una nota que decia "entra a la consola y crea
# una politica". Una alerta que hay que acordarse de crear a mano no es una
# alerta. Este script la crea.
#
# ## Los dos modos de fallar
#
# Un job diario falla de dos maneras y hacen falta dos politicas, porque la
# segunda no dispara ninguna alarma por si sola:
#
#   1. CORRIO Y FALLO   - el cierre devolvio 500. Pasa si la cadena esta rota
#                         (se detecto manipulacion y NO se anclo) o si el
#                         anclaje no pudo publicarse.
#   2. NO CORRIO        - silencio. El job se deshabilito, se borro, o el
#                         scheduler dejo de disparar. Nadie devuelve error
#                         porque nadie corre: es el fallo que se descubre por
#                         casualidad tres semanas despues.
#
# El segundo es el que importa y el que nadie configura.
#
# Uso:
#   powershell -ExecutionPolicy Bypass -File ./configurar_alertas.ps1 -Email tu@correo.com

param(
    [Parameter(Mandatory = $true)]
    [string]$Email
)

$PROJECT_ID = "project-d0428141-1b39-47af-9bc"
$SERVICIO = "agente-cfdi-run"

# Misma disciplina que deploy.ps1: SDK portatil, dos cuentas en la maquina.
$SDK_BIN = "D:\CORD\tools\google-cloud-sdk\bin"
if (Test-Path $SDK_BIN) { $env:Path = "$env:Path;$SDK_BIN" }
if (-not $env:CLOUDSDK_CONFIG) { $env:CLOUDSDK_CONFIG = "D:\CORD\tools\gcloud-config-ricardo" }

Write-Host "============================================="
Write-Host " Alertas del cierre diario (2.11)"
Write-Host " Proyecto: $PROJECT_ID"
Write-Host " Avisos a: $Email"
Write-Host "============================================="

# --- 1. Metricas basadas en logs -------------------------------------------
#
# Se cuentan las peticiones al endpoint del cierre, separadas por resultado.
# Van sobre los logs de Cloud Run y no sobre los del Scheduler a proposito: el
# Scheduler solo sabe que recibio un 200, mientras que Cloud Run distingue un
# cierre que anclo de uno que encontro la cadena rota.

Write-Host "`n[1/3] Metricas basadas en logs..."

$FILTRO_BASE = @"
resource.type="cloud_run_revision"
resource.labels.service_name="$SERVICIO"
httpRequest.requestUrl:"/api/cierre-diario"
"@

$metricas = @(
    @{
        nombre      = "cierre_diario_fallido"
        descripcion = "Cierres diarios que devolvieron 5xx: cadena rota o anclaje imposible"
        filtro      = "$FILTRO_BASE`nhttpRequest.status>=500"
    },
    @{
        nombre      = "cierre_diario_exitoso"
        descripcion = "Cierres diarios que terminaron bien. Su ausencia es la alerta."
        filtro      = "$FILTRO_BASE`nhttpRequest.status=200"
    }
)

foreach ($m in $metricas) {
    $existe = gcloud logging metrics describe $m.nombre --project=$PROJECT_ID 2>$null
    if ($existe) {
        Write-Host "   ya existe: $($m.nombre)"
        continue
    }
    gcloud logging metrics create $m.nombre `
        --description=$m.descripcion `
        --log-filter=$m.filtro `
        --project=$PROJECT_ID
    if ($?) { Write-Host "   creada: $($m.nombre)" }
}

# --- 2. Canal de notificacion ----------------------------------------------

Write-Host "`n[2/3] Canal de notificacion..."

# Igual que con las politicas: se listan nombre y correo, y se compara aqui. Un
# --filter sobre labels.email_address no casa, y el sintoma es un canal nuevo por
# cada corrida — sin error, solo duplicados que nadie mira.
$CANAL = gcloud alpha monitoring channels list `
    --project=$PROJECT_ID `
    --format="csv[no-heading](name,labels.email_address)" 2>$null |
    Where-Object { $_ -like "*,$Email" } |
    ForEach-Object { $_.Split(",")[0] } |
    Select-Object -First 1

if (-not $CANAL) {
    $CANAL = gcloud alpha monitoring channels create `
        --display-name="Cierre diario - Agente CFDI" `
        --type=email `
        --channel-labels="email_address=$Email" `
        --project=$PROJECT_ID `
        --format="value(name)"
    Write-Host "   creado: $CANAL"
} else {
    Write-Host "   ya existe: $CANAL"
}

if (-not $CANAL) {
    Write-Host "`nNo se pudo crear el canal. Sin canal, una politica no avisa a nadie." -ForegroundColor Red
    exit 1
}

# --- 3. Politicas de alerta ------------------------------------------------

Write-Host "`n[3/3] Politicas de alerta..."

$tmp = Join-Path $env:TEMP "alertas-cfdi"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

# Politica A: corrio y fallo.
#
# El umbral es CERO y la ventana 5 minutos: un solo cierre fallido tiene que
# avisar. No es una metrica de capacidad donde un pico se tolera; es un evento
# que ocurre una vez al dia y que, cuando ocurre mal, significa que hay una
# raiz sin publicar o una manipulacion detectada.
$politicaFallo = @"
{
  "displayName": "Cierre diario FALLIDO (cadena rota o anclaje imposible)",
  "documentation": {
    "content": "El cierre diario devolvio 5xx. Dos causas posibles:\n\n1. CADENA ROTA: se detecto que un registro fue alterado y el sistema se nego a anclar. NO reintentar: publicar la raiz de una cadena manipulada dejaria constancia permanente de datos corruptos. Revisar /auditoria/semaforo, que nombra la fila exacta.\n\n2. ANCLAJE IMPOSIBLE: la red no respondio o la wallet se quedo sin gas. Esto si se reintenta.\n\nDistinguirlas: el cuerpo de la respuesta trae 'estado'.",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "Al menos un cierre con 5xx",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/cierre_diario_fallido\" AND resource.type=\"cloud_run_revision\"",
      "comparison": "COMPARISON_GT",
      "thresholdValue": 0,
      "duration": "0s",
      "aggregations": [{
        "alignmentPeriod": "300s",
        "perSeriesAligner": "ALIGN_SUM"
      }]
    }
  }],
  "combiner": "OR",
  "notificationChannels": ["$CANAL"],
  "alertStrategy": { "autoClose": "86400s" }
}
"@

# Politica B: no corrio.
#
# NO se usa una condicion de ausencia. El maximo que admite la API son 23h30m y
# el job corre cada 24h exactas: la ventana venceria media hora ANTES de cada
# cierre y la alerta gritaria todos los dias. Una alerta que avisa a diario es
# una alerta que se aprende a ignorar, y entonces no avisa de nada.
#
# En su lugar se suma la metrica sobre una ventana movil de 24 h y se exige que
# haya al menos un cierre. Esa ventana siempre contiene el ultimo cierre, asi
# que solo baja a cero cuando de verdad se salto uno. El `duration` de 30 min da
# margen para un cierre que se retrase sin levantar a nadie de la cama.
#
# `evaluationMissingData: ACTIVE` es lo que hace que "no hay datos" cuente como
# violacion. Sin eso, un job borrado no generaria logs, no habria serie que
# evaluar, y el silencio total —el fallo que esta politica existe para cazar—
# pasaria desapercibido.
$politicaSilencio = @"
{
  "displayName": "Cierre diario NO CORRIO en 24 h",
  "documentation": {
    "content": "No hubo ningun cierre diario exitoso en las ultimas 24 horas.

Esta es la falla silenciosa: nadie devolvio error porque nadie corrio. Revisar en este orden:

1. gcloud scheduler jobs describe job-cierre-diario --location us-central1 (sigue ENABLED?)
2. Que el servicio de Cloud Run responda.
3. Que la URI del job siga apuntando al servicio.

OJO: un dia sin movimientos NO cae aqui. El cierre responde 200 con estado sin_movimientos y la metrica lo cuenta como exitoso, que es lo correcto: el job corrio e hizo su trabajo.",
    "mimeType": "text/markdown"
  },
  "conditions": [{
    "displayName": "Menos de un cierre exitoso en 24 h",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/cierre_diario_exitoso\" AND resource.type=\"cloud_run_revision\"",
      "comparison": "COMPARISON_LT",
      "thresholdValue": 1,
      "duration": "1800s",
      "evaluationMissingData": "EVALUATION_MISSING_DATA_ACTIVE",
      "aggregations": [{
        "alignmentPeriod": "86400s",
        "perSeriesAligner": "ALIGN_SUM"
      }]
    }
  }],
  "combiner": "OR",
  "notificationChannels": ["$CANAL"],
  "alertStrategy": { "autoClose": "604800s" }
}
"@

$politicas = @(
    @{ archivo = "fallo.json";    contenido = $politicaFallo;    nombre = "Cierre diario FALLIDO (cadena rota o anclaje imposible)" },
    @{ archivo = "silencio.json"; contenido = $politicaSilencio; nombre = "Cierre diario NO CORRIO en 24 h" }
)

foreach ($p in $politicas) {
    # Se listan los displayName y se compara en PowerShell en vez de pasarle un
    # --filter con comillas anidadas a gcloud: ese filtro no casaba nunca y la
    # primera version de este script sembro una politica duplicada por corrida.
    $existentes = gcloud alpha monitoring policies list `
        --project=$PROJECT_ID `
        --format="value(displayName)" 2>$null

    if ($existentes -contains $p.nombre) {
        Write-Host "   ya existe: $($p.nombre)"
        continue
    }

    $ruta = Join-Path $tmp $p.archivo
    $p.contenido | Out-File -FilePath $ruta -Encoding utf8
    gcloud alpha monitoring policies create --policy-from-file=$ruta --project=$PROJECT_ID
    if ($?) { Write-Host "   creada: $($p.nombre)" }
}

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue

Write-Host "`n============================================="
Write-Host " Listo. Comprobar con:"
Write-Host "   gcloud alpha monitoring policies list --project=$PROJECT_ID --format='table(displayName,enabled)'"
Write-Host ""
Write-Host " La politica de silencio tarda 24 h en poder dispararse: necesita"
Write-Host " ese hueco para saber que hubo ausencia. La de fallo avisa enseguida."
Write-Host "============================================="
