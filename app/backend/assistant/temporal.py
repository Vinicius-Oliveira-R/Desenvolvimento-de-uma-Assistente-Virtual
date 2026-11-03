import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.backend.core.clock import Clock

TURNOS: dict[str, tuple[str, str]] = {
    "manha": ("06:00", "12:00"),
    "tarde": ("12:00", "18:00"),
    "noite": ("18:00", "23:00"),
}

_DATA_BR = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?$")
_DATA_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_HORA = re.compile(r"(\d{1,2})(?:\s*(?:h|:)\s*(\d{2}))?")


@dataclass(frozen=True)
class IntervaloDatas:
    inicio: date
    fim: date


class TemporalResolver:
    def __init__(self, clock: Clock):
        self._clock = clock

    @property
    def hoje(self) -> date:
        return self._clock.today()

    def data_explicita(self, texto: str) -> date | None:
        if match := _DATA_ISO.match(texto):
            return self._criar_data(int(match[1]), int(match[2]), int(match[3]))
        if not (match := _DATA_BR.match(texto)):
            return None
        dia, mes, ano = int(match[1]), int(match[2]), match[3]
        if ano:
            return self._criar_data(int(ano) + 2000 if len(ano) == 2 else int(ano), mes, dia)
        candidata = self._criar_data(self.hoje.year, mes, dia)
        if candidata and candidata < self.hoje:
            return self._criar_data(self.hoje.year + 1, mes, dia)
        return candidata

    def data_relativa(self, chave: str) -> date:
        deslocamentos = {"hoje": 0, "amanha": 1, "depois_de_amanha": 2}
        return self.hoje + timedelta(days=deslocamentos[chave])

    def dia_do_mes(self, dia: int) -> date | None:
        ano, mes = self.hoje.year, self.hoje.month
        for _ in range(2):
            candidata = self._criar_data(ano, mes, dia)
            if candidata and candidata >= self.hoje:
                return candidata
            ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
        return None

    def dia_da_semana(self, indice: int) -> date:
        dias_ate = (indice - self.hoje.weekday()) % 7 or 7
        return self.hoje + timedelta(days=dias_ate)

    def periodo(self, chave: str) -> IntervaloDatas:
        if chave == "proxima_semana":
            inicio = self.hoje + timedelta(days=7 - self.hoje.weekday())
            return IntervaloDatas(inicio, inicio + timedelta(days=6))
        if chave == "esta_semana":
            return IntervaloDatas(self.hoje, self.hoje + timedelta(days=6 - self.hoje.weekday()))
        if chave == "proximo_mes":
            ano, mes = (self.hoje.year + 1, 1) if self.hoje.month == 12 else (self.hoje.year, self.hoje.month + 1)
            return IntervaloDatas(date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1]))
        raise ValueError(f"Período desconhecido: {chave}")

    @staticmethod
    def hora(texto: str, turno: str | None = None) -> str | None:
        if "meio" in texto and "dia" in texto:
            return "12:00"
        if not (match := _HORA.search(texto)):
            return None
        horas, minutos = int(match[1]), int(match[2] or 0)
        if turno in ("tarde", "noite") and horas < 12 and horas + 12 <= 23:
            horas += 12
        if horas > 23 or minutos > 59:
            return None
        return f"{horas:02d}:{minutos:02d}"

    @staticmethod
    def _criar_data(ano: int, mes: int, dia: int) -> date | None:
        try:
            return date(ano, mes, dia)
        except ValueError:
            return None
