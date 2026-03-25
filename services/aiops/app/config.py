from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-5.4"
    OPENAI_FALLBACK_MODEL: str = "gpt-4.1"
    AGENT_MAX_ITERATIONS: int = 20

    KEEP_API_URL: str = "http://keep-api:8080"
    KEEP_API_KEY: str = ""

    CHROMA_URL: str = "http://chromadb:8000"
    CHROMA_COLLECTION: str = "aiops_knowledge"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    OPENRCA_DATA_DIR: str = "/data/openrca"
    SQLITE_PATH: str = "/data/aiops.db"

    DRAIN_SIMILARITY: float = 0.4
    DRAIN_DEPTH: int = 4
    DRAIN_MAX_CLUSTERS: int = 1024

    ANOMALY_WINDOW_SECONDS: int = 300
    ANOMALY_CONTAMINATION: float = 0.1


@lru_cache
def get_settings() -> Settings:
    return Settings()
