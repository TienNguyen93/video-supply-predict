# ============================================================
# MLflow Dockerfile
# Lightweight MLflow tracking server backed by local artifact store.
# ============================================================
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    mlflow>=2.12.0 \
    boto3>=1.34.0 \
    psycopg2-binary>=2.9.9

# Create artifact store directory
RUN mkdir -p /mlflow/artifacts /mlflow/mlruns

WORKDIR /mlflow

# Expose the MLflow UI port
EXPOSE 5000

CMD ["mlflow", "server", \
     "--host", "0.0.0.0", \
     "--port", "5000", \
     "--backend-store-uri", "sqlite:///mlflow/mlflow.db", \
     "--default-artifact-root", "/mlflow/artifacts", \
     "--serve-artifacts"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1
