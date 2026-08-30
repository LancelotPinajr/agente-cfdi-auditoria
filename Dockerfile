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
# --timeout y --retries: el arbol de google-adk son decenas de paquetes y una
# lectura lenta de PyPI tumba la build entera (paso en la build 5a0dbdce del
# 20-ago). El valor por omision de pip son 15 s, corto para un archivo grande.
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt

# Copiar el código
COPY . .

# Instalar el paquete `agente_cfdi` que vive en src/ (tarea 1.13).
#
# `--no-deps` es deliberado: las versiones ya quedaron fijadas arriba y no se
# vuelven a resolver. Sin este paso el motor de auditoría viaja en la imagen
# —`COPY . .` lo trae— pero `import agente_cfdi` falla, que es exactamente por
# qué la URL pública no hacía nada de lo que el proyecto promete.
# `--no-build-isolation` usa el setuptools que ya quedo instalado arriba en
# vez de abrir un entorno aislado y volver a bajarlo. `--no-deps` no cubre
# las dependencias de CONSTRUCCION, que es un subproceso aparte y no hereda
# el --timeout: por ahi se cayo la build del 20-ago dos veces seguidas.
RUN pip install --no-cache-dir --timeout 120 --retries 5 --no-deps --no-build-isolation .

# Exponer el puerto que usará Cloud Run (8080 por defecto)
EXPOSE 8080

# Comando para correr la app con uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
