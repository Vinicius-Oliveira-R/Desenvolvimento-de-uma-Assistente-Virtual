"""Idade em anos completos a partir do cadastro; não comprova identidade nem capacidade."""
import re
from datetime import date

IDADE_MAXIMA_PLAUSIVEL = 130
_DATA_BR = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")


def idade_em_anos(nascimento: date, hoje: date) -> int:
    """Conta o ano só depois do aniversário; quem nasceu em 29/02 completa o ano em 01/03."""
    ainda_nao_fez_aniversario = (hoje.month, hoje.day) < (nascimento.month, nascimento.day)
    return hoje.year - nascimento.year - ainda_nao_fez_aniversario


def ler_data_nascimento(valor: str | None) -> date | None:
    """Aceita o ISO atual e o dd/mm/aaaa de cadastros antigos; qualquer outro valor é desconhecido."""
    texto = (valor or "").strip()
    try:
        if match := _DATA_BR.match(texto):
            return date(int(match[3]), int(match[2]), int(match[1]))
        return date.fromisoformat(texto)
    except ValueError:
        return None


def idade_do_cadastro(valor: str | None, hoje: date) -> int | None:
    nascimento = ler_data_nascimento(valor)
    if nascimento is None or nascimento > hoje:
        return None
    idade = idade_em_anos(nascimento, hoje)
    return idade if idade <= IDADE_MAXIMA_PLAUSIVEL else None
