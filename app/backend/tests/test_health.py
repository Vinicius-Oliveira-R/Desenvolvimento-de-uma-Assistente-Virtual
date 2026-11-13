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


def test_inicializacao_nao_depende_do_classificador(monkeypatch) -> None:
    import app.backend.assistant.orchestrator as module
    def broken():
        raise RuntimeError("ML indisponível na inicialização")
    monkeypatch.setattr(module, "get_profile_classifier", broken)
    with TestClient(app) as running:
        assert running.get("/health").json() == {"status": "ok"}
