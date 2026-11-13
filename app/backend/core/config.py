from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "Assistente Clínico"
    environment: Literal["production", "development", "test"] = "production"
    debug: bool = False
    database_url: str = Field(repr=False)
    secret_key: str = Field(min_length=32, repr=False)
    algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1, le=480)
    bcrypt_rounds: int = Field(default=12, ge=12, le=16)
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(default=["http://127.0.0.1:8001", "http://localhost:8001"])
    timezone: str = "America/Sao_Paulo"
    login_max_attempts: int = Field(default=5, ge=1, le=100)
    login_window_seconds: int = Field(default=900, ge=60, le=3600)
    login_ip_max_attempts: int = Field(default=50, ge=5, le=1000)
    ml_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    ml_retry_seconds: float = Field(default=60.0, ge=1, le=600)

    @field_validator("secret_key")
    @classmethod
    def validar_segredo(cls, value: str) -> str:
        if value != value.strip() or len(set(value)) < 12 or any(
            marker in value.lower() for marker in ("troque-por", "sua_chave", "changeme", "change-me")
        ):
            raise ValueError("SECRET_KEY deve ser uma chave aleatória exclusiva, com pelo menos 32 caracteres")
        return value

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", case_sensitive=False,
        extra="ignore", hide_input_in_errors=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
