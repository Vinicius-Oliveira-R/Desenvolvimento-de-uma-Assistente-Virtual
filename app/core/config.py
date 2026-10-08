from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Assistente Clínico"
    debug: bool = False
    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@localhost:5432/assistente_clinico")
    secret_key: str = "troque-por-uma-chave-segura"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
