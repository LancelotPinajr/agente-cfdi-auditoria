# Usa una imagen oficial ligera de Python
FROM python:3.11-slim

# Evita que Python escriba archivos .pyc
ENV PYTHONDONTWRITEBYTECODE 1
# Fuerza a que stdout y stderr vayan directo a la terminal
ENV PYTHONUNBUFFERED 1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias (versiones exactas, ver requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código
COPY . .

# Instalar el paquete `agente_cfdi` que vive en src/ (tarea 1.13).
#
# `--no-deps` es deliberado: las versiones ya quedaron fijadas arriba y no se
# vuelven a resolver. Sin este paso el motor de auditoría viaja en la imagen
# —`COPY . .` lo trae— pero `import agente_cfdi` falla, que es exactamente por
# qué la URL pública no hacía nada de lo que el proyecto promete.
RUN pip install --no-cache-dir --no-deps .

# Exponer el puerto que usará Cloud Run (8080 por defecto)
EXPOSE 8080

# Comando para correr la app con uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
