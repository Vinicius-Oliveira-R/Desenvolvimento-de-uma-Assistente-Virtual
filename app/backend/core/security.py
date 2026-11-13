from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.backend.core.config import get_settings

settings = get_settings()
BCRYPT_LIMITE_BYTES = 72


def verify_password(plain_password: str, hashed_password: str) -> bool:
    senha = plain_password.encode("utf-8")
    if len(senha) > BCRYPT_LIMITE_BYTES:
        return False
    try:
        return bcrypt.checkpw(senha, hashed_password.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return False


def get_password_hash(password: str) -> str:
    value = password.encode("utf-8")
    if not value or len(value) > BCRYPT_LIMITE_BYTES:
        raise ValueError("Senha vazia ou acima do limite de 72 bytes")
    return bcrypt.hashpw(value, bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode("ascii")


def create_access_token(subject: str, token_version: int = 0) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, "ver": token_version}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token_claims(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm],
            options={"require_exp": True, "require_sub": True},
        )
        if not str(payload["sub"]).isdigit() or type(payload.get("ver")) is not int:
            raise ValueError("Token inválido ou expirado")
        return payload
    except (JWTError, KeyError, TypeError) as exc:
        raise ValueError("Token inválido ou expirado") from exc


def decode_access_token(token: str) -> str:
    return decode_token_claims(token)["sub"]
