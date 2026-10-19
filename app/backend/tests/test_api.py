import os

os.environ["DATABASE_URL"] = "sqlite:///./test_assistente_clinico.db"

from fastapi.testclient import TestClient

from app.backend.core.database import Base, engine
from app.backend.main import app

client = TestClient(app)


def setup_function() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_register_and_login() -> None:
    payload = {"nome": "Ana", "email": "ana@email.com", "senha": "senha123", "tipo": "paciente"}
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["email"] == payload["email"]
    assert "token" in data

    login_response = client.post("/auth/login", json={"email": payload["email"], "senha": payload["senha"]})
    assert login_response.status_code == 200, login_response.text
    assert "token" in login_response.json()


def test_patient_and_doctor_flow() -> None:
    register = client.post(
        "/auth/register",
        json={"nome": "Paciente Teste", "email": "paciente@email.com", "senha": "senha123", "tipo": "paciente"},
    )
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    patient = client.post(
        "/pacientes",
        headers=headers,
        json={
            "nome": "Paciente Teste",
            "cpf": "12345678900",
            "data_nascimento": "1990-01-10",
            "telefone": "11999999999",
        },
    )
    assert patient.status_code == 201, patient.text

    doctor = client.post(
        "/medicos",
        headers=headers,
        json={"nome": "Dr. João", "crm": "CRM-SP-1234", "especialidade": "Cardiologia"},
    )
    assert doctor.status_code == 201, doctor.text

    horario = client.post(
        "/horarios",
        headers=headers,
        json={"medico_id": doctor.json()["id"], "data": "2026-10-10", "hora_inicio": "09:00", "hora_fim": "09:30"},
    )
    assert horario.status_code == 201, horario.text

    consulta = client.post(
        "/consultas",
        headers=headers,
        json={
            "paciente_id": patient.json()["id"],
            "medico_id": doctor.json()["id"],
            "horario_id": horario.json()["id"],
            "data": "2026-10-10",
            "observacao": "Consulta inicial",
        },
    )
    assert consulta.status_code == 201, consulta.text
    assert consulta.json()["status"] == "agendada"


def test_consultation_conflict() -> None:
    register = client.post(
        "/auth/register",
        json={"nome": "Paciente Conflito", "email": "paciente2@email.com", "senha": "senha123", "tipo": "paciente"},
    )
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    patient = client.post(
        "/pacientes",
        headers=headers,
        json={"nome": "Paciente Conflito", "cpf": "11111111111", "data_nascimento": "1985-02-02", "telefone": "11999999998"},
    )
    doctor = client.post(
        "/medicos",
        headers=headers,
        json={"nome": "Dra. Maria", "crm": "CRM-SP-4321", "especialidade": "Neurologia"},
    )
    slot = client.post(
        "/horarios",
        headers=headers,
        json={"medico_id": doctor.json()["id"], "data": "2026-11-05", "hora_inicio": "14:00", "hora_fim": "14:30"},
    )

    first = client.post(
        "/consultas",
        headers=headers,
        json={
            "paciente_id": patient.json()["id"],
            "medico_id": doctor.json()["id"],
            "horario_id": slot.json()["id"],
            "data": "2026-11-05",
            "observacao": "Primeira",
        },
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/consultas",
        headers=headers,
        json={
            "paciente_id": patient.json()["id"],
            "medico_id": doctor.json()["id"],
            "horario_id": slot.json()["id"],
            "data": "2026-11-05",
            "observacao": "Segunda",
        },
    )
    assert second.status_code == 409, second.text


def test_cancel_and_update_require_confirmation() -> None:
    register = client.post(
        "/auth/register",
        json={"nome": "Paciente Confirmação", "email": "confirmacao@email.com", "senha": "senha123", "tipo": "paciente"},
    )
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    patient = client.post(
        "/pacientes",
        headers=headers,
        json={"nome": "Paciente Confirmação", "cpf": "22222222222", "data_nascimento": "1987-07-12", "telefone": "11998989898"},
    )
    doctor = client.post(
        "/medicos",
        headers=headers,
        json={"nome": "Dr. Carlos", "crm": "CRM-SP-5555", "especialidade": "Dermatologia"},
    )
    slot = client.post(
        "/horarios",
        headers=headers,
        json={"medico_id": doctor.json()["id"], "data": "2026-12-15", "hora_inicio": "10:00", "hora_fim": "10:30"},
    )
    consulta = client.post(
        "/consultas",
        headers=headers,
        json={
            "paciente_id": patient.json()["id"],
            "medico_id": doctor.json()["id"],
            "horario_id": slot.json()["id"],
            "data": "2026-12-15",
            "observacao": "Consulta para confirmação",
        },
    )
    consulta_id = consulta.json()["id"]

    unconfirmed_cancel = client.request("DELETE", f"/consultas/{consulta_id}", json={"confirmado": False})
    assert unconfirmed_cancel.status_code == 400, unconfirmed_cancel.text

    confirmed_cancel = client.request("DELETE", f"/consultas/{consulta_id}", json={"confirmado": True})
    assert confirmed_cancel.status_code == 200, confirmed_cancel.text
    assert confirmed_cancel.json()["status"] == "cancelada"

    new_consultation = client.post(
        "/consultas",
        headers=headers,
        json={
            "paciente_id": patient.json()["id"],
            "medico_id": doctor.json()["id"],
            "horario_id": slot.json()["id"],
            "data": "2026-12-15",
            "observacao": "Nova consulta",
        },
    )
    assert new_consultation.status_code == 201, new_consultation.text
    new_id = new_consultation.json()["id"]

    unconfirmed_update = client.put(f"/consultas/{new_id}", json={"observacao": "Atualizada sem confirmação", "confirmado": False})
    assert unconfirmed_update.status_code == 400, unconfirmed_update.text

    confirmed_update = client.put(f"/consultas/{new_id}", json={"observacao": "Atualizada com confirmação", "confirmado": True})
    assert confirmed_update.status_code == 200, confirmed_update.text
    assert confirmed_update.json()["observacao"] == "Atualizada com confirmação"


def test_assistant_understands_schedule_request() -> None:
    register = client.post(
        "/auth/register",
        json={"nome": "Atendente", "email": "atendente@email.com", "senha": "senha123", "tipo": "paciente"},
    )
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    doctor = client.post(
        "/medicos",
        headers=headers,
        json={"nome": "Dr. João", "crm": "CRM-SP-7777", "especialidade": "Cardiologia"},
    )
    slot = client.post(
        "/horarios",
        headers=headers,
        json={"medico_id": doctor.json()["id"], "data": "2026-10-10", "hora_inicio": "09:00", "hora_fim": "09:30"},
    )
    patient = client.post(
        "/pacientes",
        headers=headers,
        json={"nome": "Paciente IA", "cpf": "33333333333", "data_nascimento": "1991-03-03", "telefone": "11988887777"},
    )

    response = client.post(
        "/assistant/interpret",
        json={"mensagem": "Quero agendar uma consulta com Dr. João para 2026-10-10 às 09:00 para o paciente Paciente IA"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intent"] == "agendar_consulta"
    assert payload["doctor"] == "Dr. João"
    assert payload["data"] == "2026-10-10"
    assert payload["hora"] == "09:00"
    assert payload["status"] == "slot_disponivel"
    assert payload["slot_id"] == slot.json()["id"]


def test_assistant_can_create_consultation_from_message() -> None:
    register = client.post(
        "/auth/register",
        json={"nome": "Recepcionista", "email": "recep@email.com", "senha": "senha123", "tipo": "paciente"},
    )
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    doctor = client.post(
        "/medicos",
        headers=headers,
        json={"nome": "Dra. Ana", "crm": "CRM-SP-8888", "especialidade": "Pediatria"},
    )
    slot = client.post(
        "/horarios",
        headers=headers,
        json={"medico_id": doctor.json()["id"], "data": "2026-11-20", "hora_inicio": "15:00", "hora_fim": "15:30"},
    )
    client.post(
        "/pacientes",
        headers=headers,
        json={"nome": "Maria Souza", "cpf": "44444444444", "data_nascimento": "1992-05-11", "telefone": "11977776666"},
    )

    response = client.post(
        "/assistant/agendar",
        json={"mensagem": "Agende uma consulta com Dra. Ana para 2026-11-20 às 15:00 para Maria Souza"},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["status"] == "agendada"
    assert payload["medico_id"] == doctor.json()["id"]
    assert payload["horario_id"] == slot.json()["id"]
    assert payload["observacao"] == "Agendamento realizado pelo assistente"


def test_assistant_recommends_best_slot() -> None:
    register = client.post(
        "/auth/register",
        json={"nome": "Recepcionista", "email": "recomendacao@email.com", "senha": "senha123", "tipo": "paciente"},
    )
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    cardiologist = client.post(
        "/medicos",
        headers=headers,
        json={"nome": "Dr. Carlos", "crm": "CRM-SP-9000", "especialidade": "Cardiologia"},
    )
    client.post(
        "/horarios",
        headers=headers,
        json={"medico_id": cardiologist.json()["id"], "data": "2026-12-02", "hora_inicio": "08:30", "hora_fim": "09:00"},
    )

    neurologist = client.post(
        "/medicos",
        headers=headers,
        json={"nome": "Dra. Fernanda", "crm": "CRM-SP-9001", "especialidade": "Neurologia"},
    )
    client.post(
        "/horarios",
        headers=headers,
        json={"medico_id": neurologist.json()["id"], "data": "2026-12-02", "hora_inicio": "08:30", "hora_fim": "09:00"},
    )

    response = client.post(
        "/assistant/recomendar",
        json={"mensagem": "Preciso de uma consulta de cardiologia com a maior rapidez possível"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["especialidade"] == "Cardiologia"
    assert payload["medico"] == "Dr. Carlos"
    assert payload["data"] == "2026-12-02"
    assert payload["hora"] == "08:30"
    assert "Sugestão" in payload["mensagem"]
