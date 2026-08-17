from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
from google import genai

app = FastAPI(title="Agente CFDI Auditoría")

# --- Configuración Gemini ---
# Prioriza Variable de Entorno, luego usa los defaults
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-d0428141-1b39-47af-9bc")
LOCATION = os.environ.get("GOOGLE_CLOUD_REGION", "global")

# Inicializamos el cliente. Si estamos en local sin GOOGLE_API_KEY, 
# se usará Vertex AI vía Application Default Credentials
try:
    if "GOOGLE_API_KEY" in os.environ:
        client = genai.Client()
    else:
        client = genai.Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION
        )
except Exception as e:
    print(f"Error inicializando genai.Client: {e}")
    client = None

# Modelos a usar en FastAPI
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    reply: str

@app.get("/")
def read_root():
    """Health check básico para Cloud Run"""
    return {"status": "ok", "service": "agente-cfdi"}

@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Endpoint de prueba para verificar Gemini (ADK esqueleto)
    """
    if not client:
        raise HTTPException(status_code=500, detail="Cliente Gemini no inicializado")
    
    try:
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=request.message,
        )
        return ChatResponse(reply=resp.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/cierre-diario")
def cierre_diario():
    """
    Este endpoint será llamado por el Cloud Scheduler (Tarea 2.9)
    """
    # TODO: Integrar lógica de auditoría y Merkle Tree (Gilfoyle Sprint 2)
    return {"status": "ok", "message": "Cierre diario ejecutado (simulado)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
