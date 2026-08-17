"""Definición del agente en ADK (tarea 1.4).

El agente vive aquí y no en `main.py` a propósito: `main.py` es transporte
—FastAPI para Cloud Run— y esto es el agente. Separarlos permite que el mismo
`root_agent` lo levante `adk run` / `adk web` en local sin arrastrar el servidor.

`root_agent` es el nombre que ADK busca por convención al cargar un directorio
de agentes.
"""

import os

from google.adk.agents import LlmAgent

# El id del modelo se lee del entorno para que no quede regado en el código.
# El default coincide con `smoke_test.py` y con el README: un id exacto, no un
# alias `*-latest`, para que la versión sea verificable por el jurado.
MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

INSTRUCCION = """\
Eres el Agente de Aseguramiento y Cesión de CFDI.

Tu trabajo es auditar comprobantes fiscales digitales (CFDI) mexicanos y
responder sobre su integridad. Operas para un financiador que necesita saber
si una factura es fiel y si ya fue cedida a alguien más.

Reglas:
- Responde en español, breve y sin adornos.
- Si no tienes un dato, dilo. No inventes UUID, RFC, montos ni fechas.
- No emites opinión financiera ni recomiendas operar: reportas hechos
  verificables sobre los comprobantes y la bitácora.
- Los RFC son datos personales. No los repitas si la pregunta no los requiere.
"""

root_agent = LlmAgent(
    name="agente_cfdi",
    model=MODELO,
    description=(
        "Audita lotes de CFDI, consulta la bitácora encadenada por hash y "
        "reporta integridad y cesiones duplicadas."
    ),
    instruction=INSTRUCCION,
    # Sprint 2: aquí entran las herramientas de auditoría (verificar cadena,
    # registrar cesión, prueba de Merkle) conforme Gilfoyle las expone.
    tools=[],
)
