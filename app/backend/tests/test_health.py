from fastapi.testclient import TestClient

from app.backend.assistant.orchestrator import get_profile_classifier
from app.backend.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Assistente Clínico API"}


def test_inicializacao_pre_aquece_o_classificador_do_assistente() -> None:
    get_profile_classifier.cache_clear()

    with TestClient(app):
        assert get_profile_classifier.cache_info().currsize == 1
