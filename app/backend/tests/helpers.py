from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient


class Conversa:
    def __init__(self, client: TestClient, headers: dict[str, str]):
        self._client = client
        self._headers = headers
        self.contexto: dict[str, Any] = {}

    def enviar(self, mensagem: str) -> dict[str, Any]:
        resposta = self._client.post(
            "/api/assistant/chat", headers=self._headers, json={"mensagem": mensagem, "contexto": self.contexto}
        )
        assert resposta.status_code == 200, resposta.text
        corpo = resposta.json()
        self.contexto = corpo["contexto"]
        return corpo


class ClinicaApi:
    def __init__(self, client: TestClient):
        self.client = client

    def cadastrar_paciente(self, nome: str, email: str, cpf: str) -> tuple[dict[str, str], int]:
        registro = self.client.post("/api/auth/register", json={"nome": nome, "email": email, "senha": "senha123"})
        assert registro.status_code == 201, registro.text
        headers = {"Authorization": f"Bearer {registro.json()['token']}"}
        paciente = self.client.post(
            "/api/pacientes",
            headers=headers,
            json={"nome": nome, "cpf": cpf, "data_nascimento": "1950-03-10", "telefone": "11999990000"},
        )
        assert paciente.status_code == 201, paciente.text
        return headers, paciente.json()["id"]

    def cadastrar_medico(self, nome: str, crm: str, especialidade: str) -> int:
        resposta = self.client.post("/api/medicos", json={"nome": nome, "crm": crm, "especialidade": especialidade})
        assert resposta.status_code == 201, resposta.text
        return resposta.json()["id"]

    def cadastrar_horario(self, medico_id: int, data: str, hora_inicio: str) -> int:
        fim = (datetime.strptime(hora_inicio, "%H:%M") + timedelta(minutes=30)).strftime("%H:%M")
        resposta = self.client.post(
            "/api/horarios", json={"medico_id": medico_id, "data": data, "hora_inicio": hora_inicio, "hora_fim": fim}
        )
        assert resposta.status_code == 201, resposta.text
        return resposta.json()["id"]

    def horario_disponivel(self, horario_id: int) -> bool:
        horarios = self.client.get("/api/horarios").json()
        return next(horario["disponivel"] for horario in horarios if horario["id"] == horario_id)

    def conversa(self, headers: dict[str, str]) -> Conversa:
        return Conversa(self.client, headers)
