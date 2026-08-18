"""Transporte HTTP del agente (Cloud Run).

Este archivo no contiene lógica de agente: la ejecución la lleva el `Runner` de
ADK sobre el `root_agent` definido en `agente/agent.py`.
"""

import os
import uuid

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Response
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from agente.agent import MODELO, root_agent
from agente_cfdi.api.app import app as app_auditoria
from agente_cfdi.api.app import cierre_diario as cierre_del_motor
from agente_cfdi.api.dependencias import ancla_actual, bitacora_actual
from agente_cfdi.api.esquemas import RespuestaDeCierre
from agente_cfdi.bitacora.almacen import Bitacora
from agente_cfdi.bitacora.anclaje import Ancla

load_dotenv()

APP_NAME = "agente-cfdi"

# --- Selección de backend: Gemini API o Vertex AI ---
# Orden de precedencia, de mayor a menor:
#   1. GOOGLE_GENAI_USE_VERTEXAI explícita — manda siempre.
#   2. GOOGLE_API_KEY presente — se usa Gemini API.
#   3. Nada de lo anterior — Vertex AI con Application Default Credentials,
#      que es como corre en Cloud Run.
#
# El paso 1 existe porque `load_dotenv()` reinyecta lo que haya en `.env`: sin
# una palanca explícita, una key muerta en ese archivo secuestra el arranque y
# no hay manera de forzar Vertex sin editarlo.
if "GOOGLE_GENAI_USE_VERTEXAI" not in os.environ and not os.environ.get(
    "GOOGLE_API_KEY"
):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"

if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true"):
    # El README documenta GOOGLE_CLOUD_REGION, pero google-genai lee
    # GOOGLE_CLOUD_LOCATION. Se acepta la primera y se traduce.
    #
    # El default es "global" y no "us-central1": verificado el 16-ago-2026 que
    # gemini-3.5-flash NO está publicado en us-central1 (devuelve 404) y sí en
    # global. us-central1 es la región del despliegue de Cloud Run, que es otra
    # cosa; confundirlas rompe el arranque.
    if not os.environ.get("GOOGLE_CLOUD_LOCATION"):
        os.environ["GOOGLE_CLOUD_LOCATION"] = os.environ.get(
            "GOOGLE_CLOUD_REGION", "global"
        )

app = FastAPI(title="Agente CFDI Auditoría")

# La sesión en memoria se pierde al reciclar la instancia de Cloud Run. Es
# suficiente para el esqueleto; el estado que importa vive en la bitácora
# encadenada, no aquí.
session_service = InMemorySessionService()

runner = Runner(
    app_name=APP_NAME,
    agent=root_agent,
    session_service=session_service,
    auto_create_session=True,
)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    user_id: str = "anonimo"


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    model: str


@app.get("/")
def read_root():
    """Health check para Cloud Run."""
    return {
        "status": "ok",
        "service": APP_NAME,
        "framework": "google-adk",
        "model": MODELO,
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Ejecuta un turno del agente ADK."""
    session_id = request.session_id or str(uuid.uuid4())
    mensaje = types.Content(role="user", parts=[types.Part(text=request.message)])

    partes: list[str] = []
    try:
        async for event in runner.run_async(
            user_id=request.user_id,
            session_id=session_id,
            new_message=mensaje,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                partes = [p.text for p in event.content.parts if p.text]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not partes:
        raise HTTPException(
            status_code=502, detail="El agente no devolvió una respuesta final"
        )

    return ChatResponse(
        reply="".join(partes), session_id=session_id, model=MODELO
    )


@app.post("/api/cierre-diario", response_model=RespuestaDeCierre)
def cierre_diario(
    dia: str | None = None,
    respuesta: Response = None,  # type: ignore[assignment]
    bitacora: Bitacora = Depends(bitacora_actual),
    ancla: Ancla = Depends(ancla_actual),
) -> RespuestaDeCierre:
    """Disparado por Cloud Scheduler (tarea 2.9).

    Hasta el 18-ago esto devolvía `«Cierre diario ejecutado (simulado)»` y no
    cerraba nada: el scheduler corría a diario contra un stub y el tablero decía
    verde. Ahora delega en el motor de auditoría, que desde la tarea 1.13 vive en
    este mismo proceso.

    **La lógica no está aquí a propósito.** Vive en `agente_cfdi.api.app`, donde
    la cubren las pruebas: este archivo importa ADK, que el CI no instala, así
    que cualquier regla escrita aquí quedaría sin probar. Este endpoint solo
    conserva la ruta que el scheduler ya conoce.
    """
    return cierre_del_motor(dia=dia, respuesta=respuesta, bitacora=bitacora, ancla=ancla)


# --- Motor de auditoría (tarea 1.13) ---
# Hasta aquí este servicio era solo el agente: el motor verificable —lector de
# CFDI, bitácora encadenada, Merkle, doble cesión— existía en `src/` con sus
# pruebas y no estaba desplegado. Montarlo es lo que hace que la URL pública
# haga lo que el proyecto promete.
#
# Se monta en `/auditoria` y no en `/api` a propósito: un `Mount` en `/api`
# compite con `/api/chat` y `/api/cierre-diario`. Hoy los ganarían por orden de
# registro, pero eso es depender del orden de las líneas de este archivo.
#
# El montaje va **al final**, después de las rutas propias, por la misma razón.
app.mount("/auditoria", app_auditoria)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
