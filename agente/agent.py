"""Definición del agente en ADK (tarea 1.4).

El agente vive aquí y no en `main.py` a propósito: `main.py` es transporte
—FastAPI para Cloud Run— y esto es el agente. Separarlos permite que el mismo
`root_agent` lo levante `adk run` / `adk web` en local sin arrastrar el servidor.

`root_agent` es el nombre que ADK busca por convención al cargar un directorio
de agentes.
"""

import os

from google.adk.agents import LlmAgent

from agente_cfdi.agente import HERRAMIENTAS

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

Sobre tus herramientas:
- **Consulta antes de afirmar.** Nunca respondas de memoria sobre el estado de
  la bitácora, un folio o la integridad: llama a la herramienta. Un número
  inventado sobre una auditoría es peor que un «no lo sé».
- Cita el dato tal como lo devolvió la herramienta. No lo redondees ni lo
  reinterpretes.
- Solo puedes **leer**. No ingestas lotes, no registras cesiones y no cierras el
  día: eso se hace por los endpoints, no por conversación. Si te lo piden,
  explica cómo hacerlo y di que tú no lo ejecutas.
- Si el semáforo está en ámbar, **explica por qué no es verde**: la cadena
  cuadra, pero su raíz no está publicada en una red real, así que por ahora solo
  demuestra que la bitácora es consistente consigo misma. No lo presentes como
  si estuviera todo comprobado.
- Si te preguntan a nombre de quién está una cesión, no lo sabes y no lo
  averiguas: que un folio esté tomado basta para frenar una operación.
"""

root_agent = LlmAgent(
    name="agente_cfdi",
    model=MODELO,
    description=(
        "Audita lotes de CFDI, consulta la bitácora encadenada por hash y "
        "reporta integridad y cesiones duplicadas."
    ),
    instruction=INSTRUCCION,
    # Las funciones viven en `agente_cfdi.agente.herramientas`, no aquí: son
    # Python plano sin un solo import de ADK, y por eso el CI —que no instala
    # ADK— puede probarlas. ADK deriva el esquema de los tipos y del docstring.
    #
    # **Todas son de solo lectura.** Ingestar, ceder y cerrar el día escriben en
    # una bitácora append-only, donde un registro mal escrito no se corrige
    # después. Una llamada alucinada dejaría un veredicto falso, firmado y
    # permanente en la cadena que este producto vende como confiable.
    tools=HERRAMIENTAS,
)
