# Evidencia — el job diario corrió (tarea 2.9 / 2.12)

**Verificado:** 17 de agosto de 2026, contra el proyecto real en GCP.
**Qué se prueba:** que Cloud Scheduler disparó solo, a su hora, y que Cloud Run
respondió 200. **Qué NO se prueba:** ver la sección final — el endpoint todavía
es un stub.

Proyecto `project-d0428141-1b39-47af-9bc` · región `us-central1` ·
servicio `agente-cfdi-run` · job `job-cierre-diario`.

---

## 1. Configuración del job

```bash
gcloud scheduler jobs describe job-cierre-diario \
  --project project-d0428141-1b39-47af-9bc --location us-central1
```

```yaml
name: projects/project-d0428141-1b39-47af-9bc/locations/us-central1/jobs/job-cierre-diario
schedule: 59 23 * * *
timeZone: America/Mexico_City
state: ENABLED
attemptDeadline: 180s
lastAttemptTime: '2026-08-17T05:59:00.829782Z'
httpTarget:
  httpMethod: POST
  uri: https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/api/cierre-diario
retryConfig:
  retryCount: 3
  minBackoffDuration: 10s
  maxBackoffDuration: 300s
  maxRetryDuration: 600s
```

`23:59 America/Mexico_City` = `05:59 UTC`. La URL es la del servicio desplegado,
no un dominio pendiente de existir.

---

## 2. Lado Scheduler — el disparo

```bash
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="job-cierre-diario"' \
  --project project-d0428141-1b39-47af-9bc --limit 5 --freshness=7d --format=json
```

Dos entradas, el par completo de una ejecución:

```json
{
  "jsonPayload": {
    "@type": "type.googleapis.com/google.cloud.scheduler.logging.AttemptStarted",
    "jobName": ".../jobs/job-cierre-diario",
    "scheduledTime": "2026-08-17T05:59:00.829782Z",
    "targetType": "HTTP",
    "url": "https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/api/cierre-diario"
  },
  "timestamp": "2026-08-17T05:59:07.340170434Z",
  "severity": "INFO"
}
```

```json
{
  "httpRequest": { "status": 200 },
  "jsonPayload": {
    "@type": "type.googleapis.com/google.cloud.scheduler.logging.AttemptFinished",
    "debugInfo": "URL_CRAWLED. Original HTTP response code number = 200",
    "jobName": ".../jobs/job-cierre-diario",
    "targetType": "HTTP",
    "url": "https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/api/cierre-diario"
  },
  "timestamp": "2026-08-17T05:59:17.301014899Z",
  "severity": "INFO"
}
```

`AttemptStarted` seguido de `AttemptFinished` con **200**, sin reintentos: el
`retryCount: 3` nunca se consumió.

---

## 3. Lado Cloud Run — la recepción

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="agente-cfdi-run" AND httpRequest.requestUrl:"cierre-diario"' \
  --project project-d0428141-1b39-47af-9bc --limit 5 --freshness=7d
```

| Timestamp | Método | Status | Latencia | User-Agent | Revisión |
|---|---|---|---|---|---|
| 2026-08-17T05:59:00.862037Z | POST | 200 | 6.502188183s | `Google-Cloud-Scheduler` | `agente-cfdi-run-00001-2x8` |

La revisión que atendió es la única existente y la que sirve el 100% del
tráfico, creada el mismo día a las `03:44:55Z` — o sea, el job pegó contra el
código actualmente desplegado, no contra uno viejo.

```bash
gcloud run revisions list --service agente-cfdi-run \
  --project project-d0428141-1b39-47af-9bc --region us-central1
```

```
NAME                       CREATION_TIMESTAMP           STATUS
agente-cfdi-run-00001-2x8  2026-08-17T03:44:55.026341Z  True
```

### Correlación

Los dos lados cuentan el mismo evento y cierran:

| | Scheduler | Cloud Run |
|---|---|---|
| Hora | `05:59:00.829782Z` (programada) | `05:59:00.862037Z` (recibida) |
| URL | `/api/cierre-diario` | `/api/cierre-diario` |
| Resultado | `AttemptFinished` 200 | `httpRequest.status` 200 |

33 ms entre la hora programada y la llegada de la petición. Los 6.5 s de
latencia son arranque en frío de la instancia, no un problema del job.

---

## 4. Qué NO prueba esto

Honestidad sobre el alcance, porque esta evidencia se va a leer junto al video:

1. **El endpoint es un stub.** `main.py:117` devuelve
   `{"status": "ok", "message": "Cierre diario ejecutado (simulado)"}` con un
   `TODO` encima. No calcula Merkle, no ancla, no toca la bitácora. Lo probado
   aquí es la **plomería**: el disparo automático llega y el servicio contesta.
   La lógica de cierre sigue del lado de Gilfoyle, sin integrar (tarea 1.13).
2. **Una sola ejecución.** El scheduler se repuntó a la URL real el 16 de
   agosto; sólo existe la corrida del 17. No hay serie histórica ni evidencia de
   idempotencia en producción.
3. **Sin autenticación.** El servicio está `--allow-unauthenticated` y el job no
   manda OIDC: cualquiera con la URL puede disparar el cierre diario. Pendiente
   de cerrar antes de meter CFDIs reales.
4. **Sin alertas.** Si mañana el job devuelve 500, nadie se entera. Eso es
   exactamente la tarea 2.11, todavía pendiente.

---

## Cómo reproducir

Con el SDK portátil de esta máquina y la config de la cuenta correcta:

```bash
export PATH="$PATH:/d/CORD/tools/google-cloud-sdk/bin"
export CLOUDSDK_CONFIG=/d/CORD/tools/gcloud-config-ricardo
gcloud scheduler jobs list --project project-d0428141-1b39-47af-9bc --location us-central1
```

Los logs de Cloud Logging tienen retención de 30 días por defecto; después del
**16 de septiembre de 2026** las consultas de arriba dejarán de devolver esta
corrida y esta página queda como el único registro.
