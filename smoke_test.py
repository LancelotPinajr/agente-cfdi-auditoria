"""Prueba de humo: confirma que el modelo responde.

Usa la misma precedencia de backend que `main.py`, para que probar aquí y correr
el agente no puedan divergir.
"""

import os
import sys

from dotenv import load_dotenv
from google import genai

load_dotenv()

MODELO = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
PROYECTO = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-d0428141-1b39-47af-9bc")

# Vertex AI por default. La vía de API key existe solo si se pide explícitamente
# y hay key: el prepago de AI Studio se agotó el 16-ago-2026, así que Vertex con
# Application Default Credentials es el camino sostenido.
usar_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "1").lower() in ("1", "true")

if usar_vertex:
    # "global" y no la región de Cloud Run: gemini-3.5-flash no está publicado
    # en us-central1 y devuelve 404 ahí.
    ubicacion = os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get(
        "GOOGLE_CLOUD_REGION", "global"
    )
    client = genai.Client(vertexai=True, project=PROYECTO, location=ubicacion)
    origen = f"Vertex AI ({PROYECTO} / {ubicacion})"
else:
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    origen = "Gemini API (key)"

try:
    resp = client.models.generate_content(model=MODELO, contents="Responde solo: ok")
except Exception as e:
    print(f"FALLO contra {origen} con {MODELO}:\n  {e}", file=sys.stderr)
    raise SystemExit(1)

print(f"{origen} | {MODELO} -> {resp.text.strip()}")
