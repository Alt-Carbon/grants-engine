FROM python:3.11-slim

WORKDIR /app

# Build context is the project root so backend.* imports resolve correctly
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Railway sets $PORT dynamically; fall back to 8000 for local docker run
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
