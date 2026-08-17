# Usa una imagen oficial ligera de Python
FROM python:3.11-slim

# Evita que Python escriba archivos .pyc
ENV PYTHONDONTWRITEBYTECODE 1
# Fuerza a que stdout y stderr vayan directo a la terminal
ENV PYTHONUNBUFFERED 1

# Directorio de trabajo
WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código
COPY . .

# Exponer el puerto que usará Cloud Run (8080 por defecto)
EXPOSE 8080

# Comando para correr la app con uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
