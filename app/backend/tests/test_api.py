from app.backend.tests.helpers import SENHA_PADRAO, ClinicaApi


def test_register_and_login(api: ClinicaApi) -> None:
    usuario = api.cadastrar_usuario("Ana", "ana@email.com")
    assert usuario["email"] == "ana@email.com"
    assert usuario["papel"] == "paciente"
    assert "token" not in usuario

    login_response = api.client.post("/api/auth/login", json={"email": "ana@email.com", "senha": SENHA_PADRAO})
    assert login_response.status_code == 200, login_response.text
    assert login_response.json()["token"]
    assert login_response.json()["papel"] == "paciente"


def test_patient_and_doctor_flow(api: ClinicaApi) -> None:
    _, paciente_id = api.cadastrar_paciente("Paciente Teste", "paciente@email.com", "12345678900")
    medico_id = api.cadastrar_medico("Dr. João", "CRM-SP-1234", "Cardiologia")
    horario_id = api.cadastrar_horario(medico_id, "2026-10-10", "09:00")

    consulta = api.client.post(
        "/api/consultas",
        headers=api.admin,
        json={
            "paciente_id": paciente_id,
            "medico_id": medico_id,
            "horario_id": horario_id,
            "data": "2026-10-10",
            "observacao": "Consulta inicial",
        },
    )
    assert consulta.status_code == 201, consulta.text
    assert consulta.json()["status"] == "agendada"


def test_consultation_conflict(api: ClinicaApi) -> None:
    _, paciente_id = api.cadastrar_paciente("Paciente Conflito", "paciente2@email.com", "11111111111")
    medico_id = api.cadastrar_medico("Dra. Maria", "CRM-SP-4321", "Neurologia")
    horario_id = api.cadastrar_horario(medico_id, "2026-11-05", "14:00")
    consulta = {"paciente_id": paciente_id, "medico_id": medico_id, "horario_id": horario_id, "data": "2026-11-05"}

    first = api.client.post("/api/consultas", headers=api.admin, json={**consulta, "observacao": "Primeira"})
    assert first.status_code == 201, first.text

    second = api.client.post("/api/consultas", headers=api.admin, json={**consulta, "observacao": "Segunda"})
    assert second.status_code == 409, second.text


def test_cancel_and_update_require_confirmation(api: ClinicaApi) -> None:
    _, paciente_id = api.cadastrar_paciente("Paciente Confirmação", "confirmacao@email.com", "22222222222")
    medico_id = api.cadastrar_medico("Dr. Carlos", "CRM-SP-5555", "Dermatologia")
    horario_id = api.cadastrar_horario(medico_id, "2026-12-15", "10:00")
    consulta = {"paciente_id": paciente_id, "medico_id": medico_id, "horario_id": horario_id, "data": "2026-12-15"}

    criada = api.client.post(
        "/api/consultas", headers=api.admin, json={**consulta, "observacao": "Consulta para confirmação"}
    )
    consulta_id = criada.json()["id"]

    unconfirmed_cancel = api.client.request(
        "DELETE", f"/api/consultas/{consulta_id}", headers=api.admin, json={"confirmado": False}
    )
    assert unconfirmed_cancel.status_code == 400, unconfirmed_cancel.text

    confirmed_cancel = api.client.request(
        "DELETE", f"/api/consultas/{consulta_id}", headers=api.admin, json={"confirmado": True}
    )
    assert confirmed_cancel.status_code == 200, confirmed_cancel.text
    assert confirmed_cancel.json()["status"] == "cancelada"

    new_consultation = api.client.post(
        "/api/consultas", headers=api.admin, json={**consulta, "observacao": "Nova consulta"}
    )
    assert new_consultation.status_code == 201, new_consultation.text
    new_id = new_consultation.json()["id"]

    unconfirmed_update = api.client.put(
        f"/api/consultas/{new_id}",
        headers=api.admin,
        json={"observacao": "Atualizada sem confirmação", "confirmado": False},
    )
    assert unconfirmed_update.status_code == 400, unconfirmed_update.text

    confirmed_update = api.client.put(
        f"/api/consultas/{new_id}",
        headers=api.admin,
        json={"observacao": "Atualizada com confirmação", "confirmado": True},
    )
    assert confirmed_update.status_code == 200, confirmed_update.text
    assert confirmed_update.json()["observacao"] == "Atualizada com confirmação"


def test_assistant_understands_schedule_request(api: ClinicaApi) -> None:
    medico_id = api.cadastrar_medico("Dr. João", "CRM-SP-7777", "Cardiologia")
    horario_id = api.cadastrar_horario(medico_id, "2026-10-10", "09:00")
    api.cadastrar_paciente("Paciente IA", "ia@email.com", "33333333333")

    response = api.client.post(
        "/api/assistant/interpret",
        json={"mensagem": "Quero agendar uma consulta com Dr. João para 2026-10-10 às 09:00 para o paciente Paciente IA"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "agendar_consulta"
    assert payload["doctor"] == "Dr. João"
    assert payload["data"] == "2026-10-10"
    assert payload["hora"] == "09:00"
    assert payload["status"] == "slot_disponivel"
    assert payload["slot_id"] == horario_id


def test_assistant_can_create_consultation_from_message(api: ClinicaApi) -> None:
    medico_id = api.cadastrar_medico("Dra. Ana", "CRM-SP-8888", "Pediatria")
    horario_id = api.cadastrar_horario(medico_id, "2026-11-20", "15:00")
    api.cadastrar_paciente("Maria Souza", "maria@email.com", "44444444444")

    response = api.client.post(
        "/api/assistant/agendar",
        json={"mensagem": "Agende uma consulta com Dra. Ana para 2026-11-20 às 15:00 para Maria Souza"},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "agendada"
    assert payload["medico_id"] == medico_id
    assert payload["horario_id"] == horario_id
    assert payload["observacao"] == "Agendamento realizado pelo assistente"


def test_assistant_recommends_best_slot(api: ClinicaApi) -> None:
    cardiologista = api.cadastrar_medico("Dr. Carlos", "CRM-SP-9000", "Cardiologia")
    api.cadastrar_horario(cardiologista, "2026-12-02", "08:30")
    neurologista = api.cadastrar_medico("Dra. Fernanda", "CRM-SP-9001", "Neurologia")
    api.cadastrar_horario(neurologista, "2026-12-02", "08:30")

    response = api.client.post(
        "/api/assistant/recomendar",
        json={"mensagem": "Preciso de uma consulta de cardiologia com a maior rapidez possível"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["especialidade"] == "Cardiologia"
    assert payload["medico"] == "Dr. Carlos"
    assert payload["data"] == "2026-12-02"
    assert payload["hora"] == "08:30"
    assert "Sugestão" in payload["mensagem"]
