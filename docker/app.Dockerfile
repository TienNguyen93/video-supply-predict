# ============================================================
# App Dockerfile — FastAPI + Streamlit
# Both services share this image; the CMD is overridden in
# docker-compose.yml to start either uvicorn or streamlit.
# ============================================================
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency manifest first for layer caching
COPY pyproject.toml README.md ./

# Install all runtime deps (no dev extras)
RUN pip install --no-cache-dir \
    duckdb>=0.10.0 \
    dbt-duckdb>=1.7.0 \
    lightgbm>=4.3.0 \
    scikit-learn>=1.4.0 \
    mlflow>=2.12.0 \
    pandas>=2.2.0 \
    numpy>=1.26.0 \
    pyarrow>=15.0.0 \
    langgraph>=0.1.0 \
    langchain-groq>=0.1.0 \
    langchain-core>=0.2.0 \
    fastapi>=0.111.0 \
    "uvicorn[standard]>=0.29.0" \
    httpx>=0.27.0 \
    streamlit>=1.35.0 \
    plotly>=5.22.0 \
    pydantic>=2.7.0 \
    pydantic-settings>=2.2.0 \
    python-dotenv>=1.0.0 \
    pyyaml>=6.0.1 \
    structlog>=24.1.0 \
    tenacity>=8.3.0 \
    rich>=13.7.0 \
    typer>=0.12.0

# Copy source code
COPY src/ ./src/
COPY configs/ ./configs/
COPY dbt/ ./dbt/

# Install project package
RUN pip install --no-cache-dir --no-deps -e .

# Default: start FastAPI (overridden for streamlit in compose)
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# Healthcheck (FastAPI /health endpoint)
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
