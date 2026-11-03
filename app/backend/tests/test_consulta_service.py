from app.backend.tests.helpers import ClinicaApi


def _agendar(api: ClinicaApi, paciente_id: int, medico_id: int, horario_id: int, data: str) -> int:
    resposta = api.client.post(
        "/api/consultas", json={"paciente_id": paciente_id, "medico_id": medico_id, "horario_id": horario_id, "data": data}
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id"]


def test_remarcacao_transfere_horario_e_libera_o_antigo(api: ClinicaApi) -> None:
    _, paciente = api.cadastrar_paciente("Ana", "ana@email.com", "12345678901")
    medico = api.cadastrar_medico("Dr. João", "CRM-SP-1", "Cardiologia")
    antigo = api.cadastrar_horario(medico, "2026-11-10", "09:00")
    novo = api.cadastrar_horario(medico, "2026-11-12", "10:00")
    consulta = _agendar(api, paciente, medico, antigo, "2026-11-10")

    resposta = api.client.put(f"/api/consultas/{consulta}", json={"horario_id": novo, "confirmado": True})

    assert resposta.status_code == 200, resposta.text
    assert (resposta.json()["horario_id"], resposta.json()["data"]) == (novo, "2026-11-12")
    assert api.horario_disponivel(antigo)
    assert not api.horario_disponivel(novo)


def test_remarcacao_para_horario_ocupado_retorna_conflito(api: ClinicaApi) -> None:
    _, ana = api.cadastrar_paciente("Ana", "ana@email.com", "12345678901")
    _, beto = api.cadastrar_paciente("Beto", "beto@email.com", "12345678902")
    medico = api.cadastrar_medico("Dr. João", "CRM-SP-1", "Cardiologia")
    horario_ana = api.cadastrar_horario(medico, "2026-11-10", "09:00")
    horario_beto = api.cadastrar_horario(medico, "2026-11-10", "09:30")
    consulta_ana = _agendar(api, ana, medico, horario_ana, "2026-11-10")
    _agendar(api, beto, medico, horario_beto, "2026-11-10")

    resposta = api.client.put(f"/api/consultas/{consulta_ana}", json={"horario_id": horario_beto, "confirmado": True})

    assert resposta.status_code == 409
    assert not api.horario_disponivel(horario_ana)


def test_cancelamento_via_atualizacao_libera_horario(api: ClinicaApi) -> None:
    _, paciente = api.cadastrar_paciente("Ana", "ana@email.com", "12345678901")
    medico = api.cadastrar_medico("Dr. João", "CRM-SP-1", "Cardiologia")
    horario = api.cadastrar_horario(medico, "2026-11-10", "09:00")
    consulta = _agendar(api, paciente, medico, horario, "2026-11-10")

    resposta = api.client.put(f"/api/consultas/{consulta}", json={"status": "cancelada", "confirmado": True})

    assert resposta.json()["status"] == "cancelada"
    assert api.horario_disponivel(horario)
    reativacao = api.client.put(f"/api/consultas/{consulta}", json={"status": "agendada", "confirmado": True})
    assert reativacao.status_code == 409


def test_agendamento_rejeita_horario_de_outro_medico(api: ClinicaApi) -> None:
    _, paciente = api.cadastrar_paciente("Ana", "ana@email.com", "12345678901")
    joao = api.cadastrar_medico("Dr. João", "CRM-SP-1", "Cardiologia")
    maria = api.cadastrar_medico("Dra. Maria", "CRM-SP-2", "Clínica Geral")
    horario_da_maria = api.cadastrar_horario(maria, "2026-11-10", "09:00")

    resposta = api.client.post(
        "/api/consultas", json={"paciente_id": paciente, "medico_id": joao, "horario_id": horario_da_maria, "data": "2026-11-10"}
    )

    assert resposta.status_code == 400
    assert api.horario_disponivel(horario_da_maria)


def test_horario_com_formato_invalido_e_rejeitado(api: ClinicaApi) -> None:
    medico = api.cadastrar_medico("Dr. João", "CRM-SP-1", "Cardiologia")

    resposta = api.client.post(
        "/api/horarios", json={"medico_id": medico, "data": "10/11/2026", "hora_inicio": "9h", "hora_fim": "09:30"}
    )

    assert resposta.status_code == 422
