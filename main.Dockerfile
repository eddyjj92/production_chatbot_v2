FROM python:3.12-slim

WORKDIR /app

COPY requirements_main.txt .
RUN pip install --no-cache-dir -r requirements_main.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]