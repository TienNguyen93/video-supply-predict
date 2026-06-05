# ============================================================
# Airflow Dockerfile
# Based on the official Apache Airflow image.
# Installs project src/ package + pipeline dependencies.
# ============================================================
ARG AIRFLOW_VERSION=2.9.2
ARG PYTHON_VERSION=3.11

FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

USER root

# System deps (duckdb needs nothing extra; good to have curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

USER airflow

# Copy and install the project package
COPY --chown=airflow:root pyproject.toml README.md /opt/airflow/
COPY --chown=airflow:root src/ /opt/airflow/src/

# Install project in editable mode so DAGs can import from src.*
# Note: --no-deps because Airflow image already pins many deps
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
    pydantic>=2.7.0 \
    pydantic-settings>=2.2.0 \
    python-dotenv>=1.0.0 \
    pyyaml>=6.0.1 \
    structlog>=24.1.0 \
    tenacity>=8.3.0 \
    httpx>=0.27.0

# Install project itself (no build isolation — already installed deps above)
RUN pip install --no-cache-dir --no-deps -e /opt/airflow/

WORKDIR /opt/airflow
