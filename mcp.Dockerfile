FROM python:3.12-slim

WORKDIR /app

COPY requirements_mcp.txt .
RUN pip install --no-cache-dir -r requirements_mcp.txt

COPY . .

CMD ["python", "mcp_server.py"]