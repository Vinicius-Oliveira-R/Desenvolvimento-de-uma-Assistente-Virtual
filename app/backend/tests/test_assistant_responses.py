from app.backend.assistant.dialogue import TipoResultado
from app.backend.assistant.responses import SimplifiedStyle, StandardStyle


def test_todo_resultado_do_dialogo_tem_resposta_nos_dois_estilos() -> None:
    assert set(SimplifiedStyle.modelos) == set(StandardStyle.modelos) == set(TipoResultado)
