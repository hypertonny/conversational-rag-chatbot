# Use official lightweight Python image
FROM python:3.12-slim

# Set environment variables for Python and HuggingFace cache
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8501 \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface \
    UV_CACHE_DIR=/root/.cache/uv

# Set working directory
WORKDIR /app

# Install system dependencies (curl for healthcheck, git, build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt-get/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy requirements FIRST to leverage Docker layer caching
COPY requirements.txt .

# 1. Install CPU-only PyTorch first (Prevents downloading 3GB+ of CUDA/NVIDIA GPU bloat)
RUN uv pip install --system torch --index-url https://download.pytorch.org/whl/cpu

# 2. Install remaining application dependencies from PyPI
RUN uv pip install --system -r requirements.txt

# Pre-download SentenceTransformer embeddings model during build into cached layer
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application source code
ARG CACHE_BUST=2.4.0
COPY . .

# Expose web server port
EXPOSE 8501

# Health check for Dokploy / Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/api/health || exit 1

# Launch FastAPI application using Uvicorn
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8501"]
