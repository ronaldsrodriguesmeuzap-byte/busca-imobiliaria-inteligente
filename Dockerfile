FROM python:3.12-slim
WORKDIR /app
RUN pip install fastapi uvicorn requests beautifulsoup4 psycopg2-binary
COPY . .
CMD ["python", "main.py"]
