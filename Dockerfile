# =========================================================
# Base Image
# =========================================================
FROM python:3.11-slim

# =========================================================
# Environment
# =========================================================
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# =========================================================
# System Dependencies
# เหมาะกับ asyncpg / uvicorn / langchain / yaml / build wheel
# =========================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# =========================================================
# Install uv (faster than pip)
# =========================================================
RUN pip install --no-cache-dir uv

# =========================================================
# Copy dependency files first (for cache layer)
# =========================================================
COPY pyproject.toml uv.lock ./

# =========================================================
# Install Python Dependencies
# =========================================================
RUN uv sync --frozen --no-dev

# =========================================================
# Copy source code
# =========================================================
COPY . .

# =========================================================
# Expose FastAPI Port
# =========================================================
EXPOSE 8000

# =========================================================
# Run App
# =========================================================
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
CMD ["uvicorn", "app.core.app_state:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]