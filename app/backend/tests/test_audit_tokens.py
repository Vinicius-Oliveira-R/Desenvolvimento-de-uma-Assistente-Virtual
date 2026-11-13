from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.backend.core.config import get_settings


@pytest.mark.parametrize("case", ["expired", "missing_exp", "missing_sub", "wrong_algorithm", "wrong_signature", "missing_version"])
def test_invalid_tokens_are_rejected_by_protected_route(api, case):
    user = api.cadastrar_usuario("Pessoa sintética", "tokens@example.com")
    settings = get_settings()
    claims = {"sub": str(user["id"]), "exp": datetime.now(timezone.utc) + timedelta(minutes=5), "ver": 0}
    if case == "expired":
        claims["exp"] = datetime.now(timezone.utc) - timedelta(minutes=5)
    elif case == "missing_exp":
        del claims["exp"]
    elif case == "missing_sub":
        del claims["sub"]
    elif case == "missing_version":
        del claims["ver"]
    token = jwt.encode(claims, "another-test-only-secret-123456789" if case == "wrong_signature" else settings.secret_key,
                       algorithm="HS512" if case == "wrong_algorithm" else "HS256")
    response = api.client.get("/api/auth/me", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 401
    assert response.json()["detail"] == "Token inválido ou expirado"


def test_seen_notifications_remain_bounded():
    from app.backend.assistant.dialogue import ResultadoDialogo, TipoResultado
    from app.backend.assistant.orchestrator import ChatOrchestrator
    from app.backend.schemas.assistant import AcaoPendente, TipoAcao
    result = ResultadoDialogo(TipoResultado.SOLICITACAO_REMARCACAO,
        acao_pendente=AcaoPendente(tipo=TipoAcao.RESPONDER_SOLICITACAO, notificacao_id=121))
    seen = ChatOrchestrator._vistas(list(range(1, 121)), result)
    assert len(seen) == 120 and seen[-1] == 121
