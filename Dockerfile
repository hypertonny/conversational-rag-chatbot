# Use official lightweight Python image
FROM python:3.12-slim

# Set environment variables for Python, Streamlit, and HuggingFace cache
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
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system torch --index-url https://download.pytorch.org/whl/cpu

# 2. Install remaining application dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# Pre-download SentenceTransformer embeddings model during build into cached layer
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application source code
COPY . .

# Expose Streamlit port
EXPOSE 8501

# Health check for Dokploy / Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Launch Streamlit app
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
