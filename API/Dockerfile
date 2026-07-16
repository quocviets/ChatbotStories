FROM python:3.11-slim

WORKDIR /workspace

# Install system dependencies for asyncpg/pgvector
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY API/requirements.txt /workspace/API/requirements.txt
RUN pip install --no-cache-dir -r /workspace/API/requirements.txt

# Copy source codes of both projects
COPY AI_engine /workspace/AI_engine
COPY API /workspace/API

# Set PYTHONPATH so FastAPI can import app from AI_engine
ENV PYTHONPATH=/workspace/AI_engine
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "API.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
