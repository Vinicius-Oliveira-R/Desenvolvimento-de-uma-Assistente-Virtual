from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.backend.core.database import Base


class LoginAttempt(Base):
    """Contadores persistentes; a chave é HMAC, sem e-mail/IP em texto simples."""
    __tablename__ = "login_attempts"
    chave: Mapped[str] = mapped_column(String(64), primary_key=True)
    inicio: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tentativas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
