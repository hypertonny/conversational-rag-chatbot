# syntax=docker/dockerfile:1

# ──────────────────────────────────────────────────────────────────────────
# Production Runtime Image
# Copies pre-compiled virtualenv and pre-baked embedding models directly from
# the base image layer, avoiding internet downloads and providing instant rebuilds.
# ──────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8501 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf \
    TRANSFORMERS_CACHE=/opt/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

WORKDIR /app

# Pre-compiled dependencies and offline embedding models
COPY --from=fahad-unifier-dashboard:latest /opt/venv /opt/venv
COPY --from=fahad-unifier-dashboard:latest /opt/hf /opt/hf

# Application source code
COPY . .

EXPOSE 8501

# Lightweight native Python health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/api/health')" || exit 1

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8501"]
