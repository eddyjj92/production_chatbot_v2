FROM python:3.12-slim

WORKDIR /app

# Instala dependencias del sistema necesarias
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements_mcp.txt .
RUN pip install --no-cache-dir -r requirements_mcp.txt

COPY . .

CMD ["python", "mcp_server.py"]
