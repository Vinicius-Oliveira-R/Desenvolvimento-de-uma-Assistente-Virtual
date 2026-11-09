from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Assistente Clínico"
    debug: bool = False
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/assistente_clinico")
    secret_key: str = "troque-por-uma-chave-segura"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(default=["http://127.0.0.1:8001", "http://localhost:8001"])
    timezone: str = "America/Sao_Paulo"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
