"""Fluxos reais do paciente: Django (sessão, formulários, templates) -> FastAPI (diálogo) -> banco de teste.

A API roda no mesmo processo, num SQLite temporário e com relógio fixo. Os cenários conferem
a mensagem exibida na tela e o estado da consulta no banco. Requer as dependências do
backend; sem elas os testes são ignorados. Nunca usar com o banco de produção.
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import httpx
from django.test import TestCase, override_settings
from django.urls import reverse

from assistant.api_client import ClinicaApiClient

RAIZ_DO_REPOSITORIO = Path(__file__).resolve().parents[3]
AGORA = datetime(2026, 11, 3, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
HTMX = {"HTTP_HX_REQUEST": "true"}


def _carregar_backend():
    """Importa a API com um banco descartável e devolve os objetos usados pelos testes."""
    try:
        import fastapi  # noqa: F401
        import spacy  # noqa: F401
    except ImportError:
        return None
    banco = Path(tempfile.gettempdir()) / "assistente_fluxo_integrado.db"
    variaveis = {
        "DATABASE_URL": f"sqlite:///{banco.as_posix()}",
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "SECRET_KEY": "ci-only-not-for-production-44ca562370d228f2ef6ea0587ce67591",
    }
    anteriores = {chave: os.environ.get(chave) for chave in variaveis}
    os.environ.update(variaveis)
    sys.path.insert(0, str(RAIZ_DO_REPOSITORIO))
    try:
        from fastapi.testclient import TestClient

        from app.backend.core.clock import FixedClock, get_clock
        from app.backend.core.config import get_settings
        from app.backend.core.database import Base, SessionLocal, engine
        from app.backend.main import app
        from app.backend.models import Consulta, Notificacao
        from app.backend.tests.helpers import SENHA_PADRAO, ClinicaApi
    finally:
        for chave, valor in anteriores.items():
            if valor is None:
                os.environ.pop(chave, None)
            else:
                os.environ[chave] = valor
    return {
        "TestClient": TestClient, "FixedClock": FixedClock, "get_clock": get_clock, "get_settings": get_settings,
        "Base": Base, "SessionLocal": SessionLocal, "engine": engine, "app": app, "Consulta": Consulta,
        "Notificacao": Notificacao, "SENHA_PADRAO": SENHA_PADRAO, "ClinicaApi": ClinicaApi,
    }


BACKEND = _carregar_backend()


class _BotoesDaTela(HTMLParser):
    """Lê os formulários dos botões de resposta como o navegador os enviaria."""

    def __init__(self) -> None:
        super().__init__()
        self.formularios: list[dict[str, str]] = []
        self._atual: dict[str, str] | None = None

    def handle_starttag(self, tag, attrs) -> None:
        atributos = dict(attrs)
        if tag == "form" and "chat-opcao" in (atributos.get("class") or ""):
            self._atual = {}
        elif tag == "input" and self._atual is not None and atributos.get("name") != "csrfmiddlewaretoken":
            self._atual[atributos["name"]] = atributos["value"]

    def handle_endtag(self, tag) -> None:
        if tag == "form" and self._atual is not None:
            self.formularios.append(self._atual)
            self._atual = None


def botoes(html: str) -> list[dict[str, str]]:
    leitor = _BotoesDaTela()
    leitor.feed(html)
    return leitor.formularios


@unittest.skipIf(BACKEND is None, "dependências do backend não instaladas")
class FluxoIntegradoDoPacienteTests(TestCase):
    def setUp(self) -> None:
        BACKEND["Base"].metadata.drop_all(bind=BACKEND["engine"])
        BACKEND["Base"].metadata.create_all(bind=BACKEND["engine"])
        app = BACKEND["app"]
        relogio = BACKEND["FixedClock"](AGORA)
        app.dependency_overrides[BACKEND["get_clock"]] = lambda: relogio
        self.addCleanup(app.dependency_overrides.pop, BACKEND["get_clock"], None)
        self.api = BACKEND["TestClient"](app)
        self.clinica = BACKEND["ClinicaApi"](self.api)
        cliente = ClinicaApiClient("http://api.teste/api", transport=httpx.MockTransport(self._encaminhar))
        patcher = mock.patch.object(ClinicaApiClient, "from_settings", return_value=cliente)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _encaminhar(self, requisicao: httpx.Request) -> httpx.Response:
        cabecalhos = {nome: valor for nome, valor in requisicao.headers.items() if nome.lower() in ("authorization", "content-type")}
        resposta = self.api.request(
            requisicao.method, requisicao.url.path, params=dict(requisicao.url.params), headers=cabecalhos,
            content=requisicao.content,
        )
        return httpx.Response(resposta.status_code, headers=resposta.headers, content=resposta.content)

    # ------------------------------------------------------------- apoio
    def _paciente(self, nascimento: str = "1950-03-10") -> int:
        _, paciente_id = self.clinica.cadastrar_paciente("Lurdes Andrade", "lurdes@email.com", "10006172547", nascimento)
        return paciente_id

    def _entrar(self) -> None:
        resposta = self.client.post(reverse("login"), {"username": "lurdes@email.com", "password": BACKEND["SENHA_PADRAO"]})
        self.assertEqual(resposta.status_code, 302)

    def _cardiologista(self, *horas: str, data: str = "2026-11-10") -> tuple[int, list[int]]:
        medico = self.clinica.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
        return medico, [self.clinica.cadastrar_horario(medico, data, hora) for hora in horas]

    def _escrever(self, mensagem: str) -> str:
        resposta = self.client.post(reverse("chat"), {"message": mensagem}, **HTMX)
        self.assertEqual(resposta.status_code, 200)
        return resposta.content.decode()

    def _tocar(self, html: str, acao: str, valor: str | None = None) -> str:
        formulario = next(f for f in botoes(html) if f["acao"] == acao and valor in (None, f.get("valor")))
        resposta = self.client.post(reverse("chat"), formulario, **HTMX)
        self.assertEqual(resposta.status_code, 200)
        return resposta.content.decode()

    def _consultas(self) -> list[tuple[int, str]]:
        Consulta = BACKEND["Consulta"]
        with BACKEND["SessionLocal"]() as db:
            return [(c.horario_id, c.status) for c in db.query(Consulta).order_by(Consulta.id)]

    # ------------------------------------------------------------- cenários
    def test_pode_repetir_nao_marca_e_a_confirmacao_cria_exatamente_uma_reserva(self) -> None:
        self._paciente()
        _, vagas = self._cardiologista("09:00", "14:00")
        self._entrar()
        self.assertContains(self.client.get(reverse("chat")), ">Marcar consulta</button>", html=False)

        lista = self._escrever("quero marcar cardiologia")
        proposta = self._tocar(lista, "escolher", "1")
        repetida = self._escrever("pode repetir?")

        self.assertIn("Calma, vou repetir.", repetida)
        self.assertNotIn("Sua consulta está marcada", repetida)
        self.assertEqual(self._consultas(), [])

        marcada = self._tocar(repetida, "confirmar_horario")
        segundo_clique = self._tocar(proposta, "confirmar_horario")

        self.assertIn("Pronto! Sua consulta está marcada.", marcada)
        self.assertNotIn("Sua consulta está marcada", segundo_clique)
        self.assertEqual(self._consultas(), [(vagas[0], "agendada")])

    def test_atualizar_a_pagina_iniciar_outra_busca_e_tocar_um_botao_antigo(self) -> None:
        paciente_id = self._paciente()
        medico, vagas = self._cardiologista("09:00", "14:00")
        existente = self.clinica.cadastrar_horario(medico, "2026-11-12", "10:00")
        self.clinica.agendar_pela_recepcao(paciente_id, medico, existente, "2026-11-12")
        self._entrar()
        self._escrever("quero marcar cardiologia")
        antiga = self._escrever("1")

        atualizada = self.client.get(reverse("chat")).content.decode()
        self.assertIn("Continuando de onde paramos.", atualizada)
        self.assertEqual(botoes(atualizada)[0]["proposta"], botoes(antiga)[0]["proposta"])
        self.assertNotIn("Olá!", atualizada)

        self.assertRedirects(self.client.post(reverse("novo_agendamento")), reverse("chat"), fetch_redirect_response=False)
        nova = self.client.get(reverse("chat")).content.decode()
        self.assertIn("Novo agendamento", nova)
        recusada = self._tocar(antiga, "confirmar_horario")

        self.assertIn("Esse botão era de uma pergunta anterior e não vale mais.", recusada)
        self.assertEqual(self._consultas(), [(existente, "agendada")])

    def test_ajuda_durante_pedido_de_troca_da_clinica_mantem_a_consulta(self) -> None:
        paciente_id = self._paciente()
        medico, vagas = self._cardiologista("09:00", "14:00")
        consulta = self.clinica.agendar_pela_recepcao(paciente_id, medico, vagas[0], "2026-11-10")
        pedido = {"tipo": "reagendamento", "horario_id": vagas[1]}
        self.api.post(f"/api/consultas/{consulta}/solicitacoes", headers=self.clinica.admin, json=pedido)
        self._entrar()

        abertura = self.client.get(reverse("chat")).content.decode()
        ajuda = self._escrever("não sei")
        mantida = self._tocar(ajuda, "manter_consulta")

        self.assertIn("Recepção pediu para mudar sua consulta.", abertura)
        self.assertEqual([f["message"] for f in botoes(abertura)], ["Confirmar troca", "Manter minha consulta"])
        self.assertIn("a clínica espera a sua resposta", ajuda)
        self.assertIn("Sua consulta continua como estava", mantida)
        self.assertEqual(self._consultas(), [(vagas[0], "agendada")])

    def test_remarcacao_que_perde_a_vaga_mantem_a_consulta_original(self) -> None:
        paciente_id = self._paciente("1954-05-20")
        medico, (sexta,) = self._cardiologista("09:00", data="2026-11-06")
        segunda = self.clinica.cadastrar_horario(medico, "2026-11-09", "15:00")
        self.clinica.agendar_pela_recepcao(paciente_id, medico, sexta, "2026-11-06")
        self._entrar()

        proposta = self._escrever("quero mudar minha consulta de sexta para segunda à tarde")
        _, outro = self.clinica.cadastrar_paciente("Beto Souza", "beto@email.com", "12345678902")
        self.clinica.agendar_pela_recepcao(outro, medico, segunda, "2026-11-09")
        resposta = self._tocar(proposta, "confirmar_troca")

        self.assertIn("Sua consulta agora: sexta-feira, 6 de novembro, às 9 horas", proposta)
        self.assertIn("Novo horário: segunda-feira, 9 de novembro, às 15 horas", proposta)
        self.assertIn("não está mais disponível", resposta)
        self.assertEqual(self._consultas(), [(sexta, "agendada"), (segunda, "agendada")])

    @override_settings(ASSISTENTE_EXIBIR_DIAGNOSTICO=True)
    def test_paciente_nao_ve_rotulo_etario_nem_probabilidade(self) -> None:
        self._paciente()
        self._cardiologista("09:00")
        self._entrar()

        telas = [self.client.get(reverse("chat")).content.decode(), self._escrever("queria marca consulta pro coração se der...")]

        for tela in telas:
            for proibido in ("IDOSO", "PADRAO", "Perfil", "probabilidade", "heurística"):
                self.assertNotIn(proibido, tela)

    def test_sessao_expirada_comeca_uma_conversa_limpa(self) -> None:
        self._paciente()
        self._cardiologista("09:00", "14:00")
        self._entrar()
        self._escrever("quero marcar cardiologia")
        self._escrever("1")

        self.client.logout()
        self.assertEqual(self.client.get(reverse("chat")).status_code, 302)
        self._entrar()
        reaberta = self.client.get(reverse("chat")).content.decode()

        self.assertIn("Olá!", reaberta)
        self.assertNotIn("Continuando de onde paramos", reaberta)
        self.assertEqual([f["acao"] for f in botoes(reaberta)], ["marcar_consulta", "minhas_consultas", "mudar_ou_cancelar"])

    def test_login_bloqueado_pela_api_mostra_o_prazo_do_retry_after(self) -> None:
        self._paciente()
        configuracao = BACKEND["get_settings"]()
        original = configuracao.login_max_attempts
        configuracao.login_max_attempts = 1
        self.addCleanup(setattr, configuracao, "login_max_attempts", original)
        errada = {"username": "lurdes@email.com", "password": "senha-errada"}

        primeira = self.client.post(reverse("login"), errada)
        with self.assertLogs("assistant.login", level="WARNING"):
            bloqueada = self.client.post(reverse("login"), errada)

        self.assertContains(primeira, "E-mail ou senha incorretos.")
        self.assertContains(bloqueada, "Muitas tentativas de entrada. Tente novamente em 15 minutos.")
