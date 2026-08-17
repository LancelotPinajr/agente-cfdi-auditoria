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

Verificado el 14-ago-2026 vía Gemini API. Migración a Vertex AI: [PENDIENTE]

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

Variables de entorno:

    $env:GOOGLE_API_KEY = "tu_key"

Prueba de humo:

    python smoke_test.py

Debe imprimir `ok`.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `GOOGLE_API_KEY` | Key de Google AI Studio |
| `GOOGLE_CLOUD_PROJECT` | `project-d0428141-1b39-47af-9bc` |
| `GOOGLE_CLOUD_REGION` | `us-central1` |
| `WALLET_PRIVATE_KEY` | Llave privada EVM (consumida vía Secret Manager) |

## Despliegue
El agente está desplegado en Cloud Run y cuenta con un esqueleto en FastAPI preparado para integrar `google-adk`.

### Despliegue Manual
Puedes desplegar la última versión con un solo comando ejecutando el script (Tarea 1.7):
```powershell
.\deploy.ps1
```

### Automatización (Cloud Scheduler)
El **Cloud Scheduler** está configurado para ejecutarse todos los días a las `23:59 CST`, enviando un POST al Cloud Run (`/api/cierre-diario`) para disparar el cierre del día, con política de reintentos automática (3 intentos máximo).
## Endpoints

- `GET /` : Health check.
- `POST /api/chat` : Endpoint de prueba ADK/Gemini. Recibe `{"message": "hola"}` y devuelve la respuesta del modelo.
- `POST /api/cierre-diario` : Endpoint llamado por Cloud Scheduler.

[PENDIENTE — 2.4, 2.8]

## Contrato en blockchain

[PENDIENTE — 2.7, 3.6]

## Licencia

MIT
