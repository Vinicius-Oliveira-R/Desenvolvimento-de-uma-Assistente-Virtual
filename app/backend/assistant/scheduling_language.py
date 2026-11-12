"""Expressões de agenda em português. Não infere diagnóstico nem inventa vagas."""

import re
import unicodedata
from dataclasses import dataclass


def normalize_schedule_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s:/]", " ", folded)).strip()


@dataclass(frozen=True)
class SchedulingLanguage:
    availability: bool = False
    booking: bool = False
    no_preference: bool = False
    own_appointments: bool = False
    decline: bool = False
    more_options: bool = False
    option: int | None = None


# As regras são restritas a consultas/agendas; não há aproximação de nomes de médicos.
_BOOKING = re.compile(
    r"\b(?:agendar|agenda|agende|agendamento|agendamentos|agend[aá]|marcar|marca|marque|marca[r]?|marcacao)\b"
    r"|\b(?:quero|queria|preciso|gostaria de)\s+(?:uma?\s+)?(?:consulta|consultar)\b"
    r"|\b(?:passar|ir)\s+(?:no|ao|num|em um)\s+medico\b"
)
_OWN = re.compile(
    r"\b(?:minha|minhas|meu|meus)\s+(?:consulta|consultas|agendamento|agendamentos)\b"
    r"|\b(?:ja marquei|ja agendei|estou agendado|estou agendada)\b"
)
_NO_PREFERENCE = re.compile(
    r"\b(?:nao sei|n sei|nao tenho preferencia|sem preferencia|tanto faz|nao conheco)\b"
    r"|\bqualquer\s+(?:medico|doutor|especialidade|consulta)\b"
    r"|\b(?:um|o) medico (?:normal|comum|geral)\b"
)
_DECLINE = re.compile(
    r"\b(?:nao|n)\s+(?:quero|preciso|vou)\s+(?:(?:mais|uma?|de)\s+)*"
    r"(?:agendar|marcar|consulta|consultar)\b"
)
_MORE = re.compile(
    r"^(?:(?:quero|pode|pode ser|tem|mostra|mostrar|ver|me mostra|me mostre)\s+)?"
    r"(?:outr[oa]s?|mais)(?:\s+(?:um|uma))?(?:\s+(?:dias?|horarios?|opcoes|opcao|vagas?))?"
    r"(?:\s+por favor)?$"
    r"|\b(?:proximas opcoes|proximos horarios|mais horarios|mais vagas|outros dias)\b"
)
_QUESTION = re.compile(r"\b(?:qual|quais|que|q|quando|como|mostra|mostrar|mostre|ver|saber|proximos?|primeiros?)\b")
_SCHEDULE_NOUN = re.compile(r"\b(?:dias?|datas?|horas?|horarios?|vagas?|disponiveis|disponivel|disponibilidade)\b")
_AVAILABILITY = re.compile(
    r"\b(?:tem|ha|existem?|sobrou|sobra|possui|haveria)\b.*"
    r"\b(?:horarios?|vagas?|consulta|consultas|disponiveis|disponivel)\b"
    r"|\b(?:dias?|datas?|horarios?|vagas?)\b.*\b(?:livres?|disponiveis|disponivel|atende|atendem)\b"
    r"|\b(?:quando|que dia|quais dias|qual dia|q dia)\b.*\b(?:consulta|consultas|atende|atendem|posso ir|posso marcar)\b"
    r"|\b(?:atende|atendem)\b.*\b(?:quando|dias?|horarios?)\b"
    r"|\bquando posso (?:ir|marcar|agendar|consultar)\b"
)
_OPTION = re.compile(
    r"^(?:(?:quero|prefiro|escolho|escolher|pode ser|vou querer)\s+)?"
    r"(?:(?:a|o)\s+)?(?:(?:opcao|numero)\s+)?(\d{1,2})(?:\s+por favor)?$"
)
_ORDINAL = re.compile(
    r"^(?:(?:quero|prefiro|escolho|pode ser|vou querer)\s+)?(?:a|o)\s+"
    r"(primeir[oa]|segund[oa]|terceir[oa]|quart[oa]|quint[oa]|sext[oa])(?:\s+opcao)?(?:\s+por favor)?$"
)


def analyze_scheduling(text: str) -> SchedulingLanguage:
    value = normalize_schedule_text(text)
    numbered = _OPTION.fullmatch(value)
    ordinal = _ORDINAL.fullmatch(value)
    option = int(numbered[1]) if numbered else None
    if ordinal:
        option = {"primeir": 1, "segund": 2, "terceir": 3, "quart": 4, "quint": 5, "sext": 6}[ordinal[1][:-1]]
    explicit_booking = bool(re.search(r"\b(?:agendar|agende|agendo|marcar|marque|marca)\b", value))
    own = bool(_OWN.search(value)) and not explicit_booking
    decline = bool(_DECLINE.search(value))
    availability = not own and not decline and bool(
        _AVAILABILITY.search(value)
        or (_QUESTION.search(value) and _SCHEDULE_NOUN.search(value))
        or re.fullmatch(r"(?:dias?|horarios?|vagas?|disponibilidade)(?: disponiveis| livres)?", value)
        or re.fullmatch(r"(?:tem|pode ser|e) (?:pra |para |de |a )?(?:hoje|amanha|tarde|manha)", value)
    )
    return SchedulingLanguage(
        availability=availability,
        booking=bool(_BOOKING.search(value)) and not own and not decline,
        no_preference=bool(_NO_PREFERENCE.search(value)),
        own_appointments=own,
        decline=decline,
        more_options=bool(_MORE.search(value)),
        option=option,
    )
