from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.backend.core.config import get_settings

settings = get_settings()
BCRYPT_LIMITE_BYTES = 72


def verify_password(plain_password: str, hashed_password: str) -> bool:
    senha = plain_password.encode()
    return len(senha) <= BCRYPT_LIMITE_BYTES and bcrypt.checkpw(senha, hashed_password.encode())


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload["sub"]
    except JWTError as exc:
        raise ValueError("Token inválido ou expirado") from exc
