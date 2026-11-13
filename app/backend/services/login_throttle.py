"""Limitador persistente de login, compartilhado entre processos da API."""
import hashlib
import hmac
import time
from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.backend.core.config import Settings, get_settings
from app.backend.models.login_attempt import LoginAttempt


class LoginThrottle:
    def __init__(self, db: Session, settings: Settings | None = None, clock: Callable[[], float] = time.time):
        self.db, self.settings, self.clock = db, settings or get_settings(), clock

    def _key(self, value: str) -> str:
        return hmac.new(self.settings.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()

    def consume(self, email: str, client: str) -> None:
        now = int(self.clock())
        window = self.settings.login_window_seconds
        buckets = sorted([
            (self._key("account:" + email.strip().lower()), self.settings.login_max_attempts),
            (self._key("client:" + client), self.settings.login_ip_max_attempts),
        ])
        dialect = self.db.get_bind().dialect.name
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        try:
            self.db.execute(delete(LoginAttempt).where(LoginAttempt.inicio < now - 2 * window))
            for key, limit in buckets:
                self.db.execute(insert(LoginAttempt).values(chave=key, inicio=now, tentativas=0).on_conflict_do_nothing())
                # A escrita também serializa o caminho SQLite; no PG a linha é bloqueada abaixo.
                self.db.execute(update(LoginAttempt).where(LoginAttempt.chave == key).values(inicio=LoginAttempt.inicio))
                bucket = self.db.execute(select(LoginAttempt).where(LoginAttempt.chave == key).with_for_update()).scalar_one()
                if bucket.inicio <= now - window:
                    bucket.inicio, bucket.tentativas = now, 0
                if bucket.tentativas >= limit:
                    retry = max(1, bucket.inicio + window - now)
                    self.db.rollback()
                    raise HTTPException(429, "Muitas tentativas; tente novamente mais tarde", headers={"Retry-After": str(retry)})
                bucket.tentativas += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def success(self, email: str) -> None:
        # Limite por origem não é zerado pelo login válido.
        self.db.execute(delete(LoginAttempt).where(LoginAttempt.chave == self._key("account:" + email.strip().lower())))
        self.db.commit()
