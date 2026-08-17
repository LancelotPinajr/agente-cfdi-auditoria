# agente-cfdi-auditoria
Agente autónomo de aseguramiento y cesión de CFDI. Auditoría con bitácora encadenada por hash, detección de doble cesión y anclaje diario verificable. Construido con Google ADK y Gemini en Cloud Run.


# Agente de Aseguramiento y Cesión de CFDI

Agente autónomo que audita lotes de CFDI, registra cada operación en una
bitácora encadenada por hash, detecta cesiones duplicadas y ancla un árbol
de Merkle diario en blockchain para verificación por terceros.

## Stack

| Componente | Tecnología |
|---|---|
| Modelo | Gemini 3.5 Flash (`gemini-3.5-flash`, versión `3.5-flash-05-2026`) |
| Framework de agentes | Google ADK |
| Infraestructura | Google Cloud Run |
| Job diario | Cloud Scheduler |
| Secretos | Secret Manager |

### Nota sobre el modelo

Se usa el id exacto y no un alias `*-latest`, para que la versión sea
verificable. Descartados: familia 2.5 (por debajo del requisito de 3.5+)
y variantes EAP/Confidential.

Verificado el 16-ago-2026 **vía Vertex AI** con Application Default Credentials.
La migración desde Gemini API está hecha: el prepago de AI Studio se agotó
(`429 RESOURCE_EXHAUSTED`) y la facturación del proyecto de GCP es independiente
de aquél, así que Vertex es la vía sostenida — y es la misma que corre en Cloud
Run, sin API key de por medio.

**La ubicación es `global`, no `us-central1`.** `gemini-3.5-flash` no está
publicado en `us-central1` y ahí devuelve 404. `us-central1` es la región del
despliegue de Cloud Run; son dos cosas distintas y confundirlas rompe el arranque.

## Trabajo preexistente

Este agente se construyó íntegramente durante el periodo de submission.
**CØRD Fiscal** es una plataforma preexistente con la que el agente integra
por HTTP, al mismo nivel que Postgres o FastAPI. No se copió código de ella.

## Requisitos

- Python 3.11+
- Cuenta de Google Cloud con facturación activa
- `gcloud` CLI instalado y autenticado

## Arranque local

En Windows, PowerShell bloquea scripts por defecto:

    Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

Entorno y dependencias:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt

Autenticación (no hace falta API key):

    gcloud auth login
    gcloud config set project project-d0428141-1b39-47af-9bc
    gcloud auth application-default login

Prueba de humo:

    python smoke_test.py

Debe imprimir la línea del backend seguida de `ok`, así:

    Vertex AI (project-d0428141-1b39-47af-9bc / global) | gemini-3.5-flash -> ok

## Variables de entorno

Ninguna es obligatoria en local: los defaults del código apuntan a Vertex con
ADC y al proyecto de abajo.

| Variable | Descripción |
|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI` | `1` para Vertex (default). Manda sobre todo lo demás |
| `GOOGLE_CLOUD_PROJECT` | `project-d0428141-1b39-47af-9bc` |
| `GOOGLE_CLOUD_REGION` | `global` — ubicación del **modelo**, no del despliegue |
| `GEMINI_MODEL` | Sobrescribe el id del modelo. Default `gemini-3.5-flash` |
| `GOOGLE_API_KEY` | Solo para la vía Gemini API. Hoy sin créditos; no se usa |
| `WALLET_PRIVATE_KEY` | Llave privada EVM (consumida vía Secret Manager) |

Si defines `GOOGLE_API_KEY` en un `.env`, ten en cuenta que `load_dotenv()` la
reinyecta en cada arranque: para forzar Vertex de todos modos, pon
`GOOGLE_GENAI_USE_VERTEXAI=1`, que tiene precedencia.

## Arquitectura del agente

El agente vive en `agente/agent.py` como `root_agent`, un `LlmAgent` de ADK —el
nombre que ADK busca por convención al cargar un directorio de agentes—, y la
ejecución la lleva un `Runner` de ADK. `main.py` es solo transporte HTTP para
Cloud Run: no contiene lógica de agente. Esa separación permite levantar el mismo
agente con `adk run` en local sin arrastrar el servidor.

## Despliegue

URL pública: **https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app**

    curl https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/
    curl -X POST https://agente-cfdi-run-xsxcmt7edq-uc.a.run.app/api/chat \
      -H "Content-Type: application/json" -d '{"message":"hola"}'

    .\deploy.ps1

El script usa `--source .`, así que Cloud Build compila el `Dockerfile` sin que
haya que construir la imagen a mano.

### Permiso que hay que dar una sola vez

En proyectos de GCP creados recientemente, la cuenta de servicio por defecto de
Compute —la que usa Cloud Build— no recibe permisos automáticamente, y el
despliegue desde fuente falla con un 403 sobre el bucket `run-sources-*`:

    gcloud projects add-iam-policy-binding project-d0428141-1b39-47af-9bc \
      --member="serviceAccount:1031368580327-compute@developer.gserviceaccount.com" \
      --role="roles/cloudbuild.builds.builder"

### Automatización (Cloud Scheduler)

El job `job-cierre-diario` dispara `POST /api/cierre-diario` todos los días a las
`23:59`, con 3 reintentos.

> **Pendiente:** hoy apunta a `https://agente-cfdi-run.a.run.app`, que no es una
> URL real de Cloud Run — nunca ha ejecutado con éxito. Hay que repuntarlo a la
> URL que Google asigne en el despliegue.

## Endpoints

- `GET /` : Health check. Devuelve el framework y el id del modelo en uso.
- `POST /api/chat` : Ejecuta un turno del agente ADK. Recibe
  `{"message": "hola"}` y acepta `session_id` opcional para hilar la conversación.
- `POST /api/cierre-diario` : Llamado por Cloud Scheduler. Hoy simulado.

[PENDIENTE — 2.4, 2.8]

## Contrato en blockchain

[PENDIENTE — 2.7, 3.6]

## Licencia

MIT
