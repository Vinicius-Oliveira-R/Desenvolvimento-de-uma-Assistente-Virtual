import os
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ["DATABASE_URL"] = f"sqlite:///{(Path(tempfile.gettempdir()) / 'assistente_clinico_test.db').as_posix()}"

import pytest
from fastapi.testclient import TestClient

from app.backend.core.clock import FixedClock, get_clock
from app.backend.core.database import Base, engine
from app.backend.main import app
from app.backend.tests.helpers import ClinicaApi

AGORA = datetime(2026, 11, 3, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


@pytest.fixture(autouse=True)
def relogio_fixo() -> Iterator[FixedClock]:
    relogio = FixedClock(AGORA)
    app.dependency_overrides[get_clock] = lambda: relogio
    yield relogio
    app.dependency_overrides.pop(get_clock, None)


@pytest.fixture
def banco_limpo() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def api(banco_limpo: None) -> ClinicaApi:
    return ClinicaApi(TestClient(app))
