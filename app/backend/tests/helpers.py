from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.backend.core.database import SessionLocal
from app.backend.core.security import create_access_token, get_password_hash
from app.backend.models import Consulta, PapelUsuario, Usuario

SENHA_PADRAO = "senha123"
# Datas fictícias: a idade do cadastro escolhe só a apresentação inicial do chat.
NASCIMENTO_IDOSO = "1950-03-10"
NASCIMENTO_ADULTO = "1995-06-15"
_HASH_SENHA_PADRAO = get_password_hash(SENHA_PADRAO)


class Conversa:
    """Reproduz o front-end: o contexto devolvido pela API volta na mensagem seguinte."""

    def __init__(self, client: TestClient, headers: dict[str, str]):
        self._client = client
        self._headers = headers
        self.contexto: dict[str, Any] = {}
        self.ultima: dict[str, Any] = {}

    def enviar(self, mensagem: str, acao: dict[str, Any] | None = None) -> dict[str, Any]:
        corpo = {"mensagem": mensagem, "contexto": self.contexto, **({"acao": acao} if acao else {})}
        return self._registrar(self._client.post("/api/assistant/chat", headers=self._headers, json=corpo))

    def tocar(self, codigo: str, valor: str | None = None, em: dict[str, Any] | None = None) -> dict[str, Any]:
        """Toca um botão exibido numa resposta (a última, por padrão), com a proposta que ele carrega."""
        origem = em or self.ultima
        botao = next(
            opcao for opcao in origem["opcoes"] if opcao["codigo"] == codigo and valor in (None, opcao["valor"])
        )
        acao = {"codigo": botao["codigo"], "proposta": botao["proposta"], "valor": botao["valor"]}
        return self.enviar(botao["rotulo"], acao)

    def retomar(self) -> dict[str, Any]:
        resposta = self._client.post("/api/assistant/retomar", headers=self._headers, json={"contexto": self.contexto})
        return self._registrar(resposta)

    def _registrar(self, resposta) -> dict[str, Any]:
        assert resposta.status_code == 200, resposta.text
        corpo = resposta.json()
        self.contexto = corpo["contexto"]
        self.ultima = corpo
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

    def cadastrar_paciente(
        self, nome: str, email: str, cpf: str, nascimento: str = NASCIMENTO_IDOSO
    ) -> tuple[dict[str, str], int]:
        # Fixtures históricas usavam sequências sem DV; converte apenas dados sintéticos dos testes.
        from app.backend.core.validation import normalize_cpf
        try:
            cpf = normalize_cpf(cpf)
        except ValueError:
            base = str(100000000 + int(cpf) % 899999999)
            for size in (10, 11):
                base += str((sum(int(d) * w for d, w in zip(base, range(size, 1, -1))) * 10 % 11) % 10)
            cpf = base
        usuario = self.cadastrar_usuario(nome, email)
        paciente = self.client.post(
            "/api/pacientes",
            headers=self.admin,
            json={
                "usuario_id": usuario["id"],
                "nome": nome,
                "cpf": cpf,
                "data_nascimento": nascimento,
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

    def agendar_pela_recepcao(self, paciente_id: int, medico_id: int, horario_id: int, data: str) -> int:
        corpo = {"paciente_id": paciente_id, "medico_id": medico_id, "horario_id": horario_id, "data": data}
        resposta = self.client.post("/api/consultas", headers=self.admin, json=corpo)
        assert resposta.status_code == 201, resposta.text
        return resposta.json()["id"]

    @staticmethod
    def consultas_no_banco() -> list[tuple[int, int, str]]:
        """(id, horario_id, status) de todas as consultas, lidas direto do banco de teste."""
        with SessionLocal() as db:
            return [(c.id, c.horario_id, c.status) for c in db.query(Consulta).order_by(Consulta.id)]
