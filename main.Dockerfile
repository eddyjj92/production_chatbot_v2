FROM python:3.12-slim

WORKDIR /app

# Instala dependencias del sistema necesarias
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copia e instala requirements primero (para mejor caché de Docker)
COPY requirements_main.txt .
RUN pip install --no-cache-dir -r requirements_main.txt

# Copia el resto del código
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]