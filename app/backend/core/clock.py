from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.backend.core.config import get_settings


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


class SystemClock:
    def __init__(self, timezone: str):
        self._zone = ZoneInfo(timezone)

    def now(self) -> datetime:
        return datetime.now(self._zone)

    def today(self) -> date:
        return self.now().date()


class FixedClock:
    def __init__(self, instante: datetime):
        self._instante = instante

    def now(self) -> datetime:
        return self._instante

    def today(self) -> date:
        return self._instante.date()


def get_clock() -> Clock:
    return SystemClock(get_settings().timezone)
