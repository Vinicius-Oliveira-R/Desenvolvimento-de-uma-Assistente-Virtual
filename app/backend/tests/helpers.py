from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.backend.core.database import SessionLocal
from app.backend.core.security import create_access_token, get_password_hash
from app.backend.models import PapelUsuario, Usuario

SENHA_PADRAO = "senha123"
_HASH_SENHA_PADRAO = get_password_hash(SENHA_PADRAO)


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
        self.admin = self.criar_usuario_no_banco("Recepção", "recepcao@email.com", PapelUsuario.ADMIN)
        self.medico = self.criar_usuario_no_banco("Dr. Plantonista", "plantonista@email.com", PapelUsuario.MEDICO)

    @staticmethod
    def criar_usuario_no_banco(nome: str, email: str, papel: PapelUsuario) -> dict[str, str]:
        """O primeiro atendente não tem quem o cadastre pela API, então nasce direto no banco."""
        with SessionLocal() as db:
            usuario = Usuario(nome=nome, email=email, senha_hash=_HASH_SENHA_PADRAO, papel=papel)
            db.add(usuario)
            db.commit()
            return ClinicaApi.cabecalho_de(usuario.id)

    @staticmethod
    def definir_papel(usuario_id: int, papel: PapelUsuario) -> None:
        with SessionLocal() as db:
            db.get(Usuario, usuario_id).papel = papel
            db.commit()

    @staticmethod
    def cabecalho_de(usuario_id: int) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(str(usuario_id))}"}

    def cadastrar_usuario(self, nome: str, email: str, papel: PapelUsuario = PapelUsuario.PACIENTE) -> dict[str, Any]:
        resposta = self.client.post(
            "/api/auth/register",
            headers=self.medico if papel == PapelUsuario.MEDICO else self.admin,
            json={"nome": nome, "email": email, "senha": SENHA_PADRAO, "papel": papel},
        )
        assert resposta.status_code == 201, resposta.text
        return resposta.json()

    def cadastrar_paciente(self, nome: str, email: str, cpf: str) -> tuple[dict[str, str], int]:
        usuario = self.cadastrar_usuario(nome, email)
        paciente = self.client.post(
            "/api/pacientes",
            headers=self.admin,
            json={
                "usuario_id": usuario["id"],
                "nome": nome,
                "cpf": cpf,
                "data_nascimento": "1950-03-10",
                "telefone": "11999990000",
            },
        )
        assert paciente.status_code == 201, paciente.text
        return self.cabecalho_de(usuario["id"]), paciente.json()["id"]

    def cadastrar_medico(self, nome: str, crm: str, especialidade: str) -> int:
        resposta = self.client.post(
            "/api/medicos", headers=self.medico, json={"nome": nome, "crm": crm, "especialidade": especialidade}
        )
        assert resposta.status_code == 201, resposta.text
        return resposta.json()["id"]

    def cadastrar_horario(self, medico_id: int, data: str, hora_inicio: str) -> int:
        fim = (datetime.strptime(hora_inicio, "%H:%M") + timedelta(minutes=30)).strftime("%H:%M")
        resposta = self.client.post(
            "/api/horarios",
            headers=self.admin,
            json={"medico_id": medico_id, "data": data, "hora_inicio": hora_inicio, "hora_fim": fim},
        )
        assert resposta.status_code == 201, resposta.text
        return resposta.json()["id"]

    def horario_disponivel(self, horario_id: int) -> bool:
        horarios = self.client.get("/api/horarios").json()
        return next(horario["disponivel"] for horario in horarios if horario["id"] == horario_id)

    def conversa(self, headers: dict[str, str]) -> Conversa:
        return Conversa(self.client, headers)
