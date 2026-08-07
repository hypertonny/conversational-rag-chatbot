# Use official lightweight Python image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8501

# Set working directory
WORKDIR /app

# Install system dependencies (curl for healthcheck, git, build-essential)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt-get/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY requirements.txt .

# Install Python packages
RUN uv pip install --system -r requirements.txt

# Copy application files
COPY . .

# Expose Streamlit port
EXPOSE 8501

# Health check for Dokploy / Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Launch Streamlit app
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
