"""Mensagem de espera para HTTP 429 a partir do cabeçalho Retry-After, sem inventar prazo."""

import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ESPERA_MAXIMA_SEGUNDOS = 24 * 60 * 60
SEM_PRAZO = "Muitas tentativas de entrada. Aguarde alguns minutos antes de tentar novamente."


def segundos_de_espera(valor: str | None, agora: datetime | None = None) -> int | None:
    """Aceita segundos (RFC 9110) ou data HTTP; valores ausentes, vencidos ou absurdos são ignorados."""
    texto = (valor or "").strip()
    if not texto:
        return None
    if texto.isascii() and texto.isdigit():
        segundos = int(texto)
    else:
        try:
            momento = parsedate_to_datetime(texto)
        except (TypeError, ValueError, IndexError):
            return None
        if momento is None or momento.tzinfo is None:
            return None
        segundos = math.ceil((momento - (agora or datetime.now(timezone.utc))).total_seconds())
    return segundos if 0 < segundos <= ESPERA_MAXIMA_SEGUNDOS else None


def mensagem_de_espera(segundos: int | None) -> str:
    if segundos is None:
        return SEM_PRAZO
    # Arredonda para cima: dizer menos tempo do que o real levaria a um novo bloqueio.
    horas, minutos = divmod(math.ceil(segundos / 60), 60)
    partes = [_plural(horas, "hora")] if horas else []
    partes += [_plural(minutos, "minuto")] if minutos else []
    return f"Muitas tentativas de entrada. Tente novamente em {' e '.join(partes)}."


def _plural(quantidade: int, unidade: str) -> str:
    return f"{quantidade} {unidade}{'' if quantidade == 1 else 's'}"
