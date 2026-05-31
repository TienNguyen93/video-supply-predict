from src.models.registry import promote_model_to_production
from src.config import settings

if __name__ == "__main__":
    promote_model_to_production(settings.mlflow_model_name, 1)
