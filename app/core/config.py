import os
from pydantic import BaseSettings, AnyUrl


class Settings(BaseSettings):
    # Database
    DATABASE_URL: AnyUrl = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/busdb",
    )

    # Redis / Celery
    REDIS_URL: AnyUrl = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: AnyUrl = os.getenv("CELERY_BROKER_URL", REDIS_URL)
    CELERY_RESULT_BACKEND: AnyUrl = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    # API
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # TCP Server
    TCP_HOST: str = os.getenv("TCP_HOST", "0.0.0.0")
    TCP_PORT: int = int(os.getenv("TCP_PORT", "5023"))

    # Misc
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "BusTracker")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
