"""
Smoke test para Vertex AI.
Verifica que la autenticación y el modelo funcionen correctamente
a través de Vertex AI (en lugar de API key directa).

Requisitos:
  1. gcloud auth application-default login  (ya autenticado)
  2. API aiplatform.googleapis.com habilitada ✅
"""

from google import genai

# --- Configuración Vertex AI ---
PROJECT_ID = "project-d0428141-1b39-47af-9bc"
LOCATION = "global"

client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=LOCATION,
)

# --- Prueba básica: generar texto ---
print("[*] Conectando a Vertex AI...")
resp = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Responde solo: ok",
)

print(f"[OK] Respuesta del modelo: {resp.text}")
print(f"[i] Modelo usado: gemini-2.5-flash")
print(f"[i] Proyecto: {PROJECT_ID}")
print(f"[i] Region: {LOCATION}")
print("\n[OK] Vertex AI funciona correctamente!")
