import json
from collections.abc import Callable
from unittest import mock

import httpx
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse

from assistant.api_client import ClinicaApiClient
from assistant.session import SessaoAssistente

HTMX = {"HTTP_HX_REQUEST": "true"}
RESPOSTA_CHAT = {
    "resposta": "Achei um horário com o médico do coração.\n1. Para marcar, escreva SIM.",
    "perfil": "IDOSO",
    "intencao": "agendar",
    "resultado": "sugestao_horario",
    "contexto": {"acao_pendente": {"tipo": "agendar", "horario_id": 7}, "probabilidade_idoso": 0.96},
}


class ApiFalsaMixin:
    def usar_api(self, handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
        requisicoes: list[httpx.Request] = []

        def registrar(requisicao: httpx.Request) -> httpx.Response:
            requisicoes.append(requisicao)
            return handler(requisicao)

        cliente = ClinicaApiClient("http://api.teste/api", transport=httpx.MockTransport(registrar))
        patcher = mock.patch.object(ClinicaApiClient, "from_settings", return_value=cliente)
        patcher.start()
        self.addCleanup(patcher.stop)
        return requisicoes

    def autenticar(self, token: str = "jwt-valido") -> None:
        usuario = get_user_model().objects.create_user("lurdes@email.com", email="lurdes@email.com", first_name="Lurdes")
        self.client.force_login(usuario)
        sessao = self.client.session
        sessao[SessaoAssistente.TOKEN] = token
        sessao.save()


def _falha_de_conexao(requisicao: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("conexão recusada", request=requisicao)


class LoginTests(ApiFalsaMixin, TestCase):
    def test_login_autentica_na_api_e_guarda_token_na_sessao(self) -> None:
        requisicoes = self.usar_api(
            lambda _: httpx.Response(200, json={"id": 1, "nome": "Lurdes", "email": "lurdes@email.com", "token": "jwt-abc"})
        )

        resposta = self.client.post(reverse("login"), {"username": "lurdes@email.com", "password": "senha123"})

        self.assertRedirects(resposta, reverse("chat"))
        self.assertEqual(self.client.session[SessaoAssistente.TOKEN], "jwt-abc")
        self.assertEqual(requisicoes[0].url.path, "/api/auth/login")
        self.assertEqual(get_user_model().objects.get(username="lurdes@email.com").first_name, "Lurdes")

    def test_login_com_credenciais_invalidas_exibe_erro(self) -> None:
        self.usar_api(lambda _: httpx.Response(401, json={"detail": "Credenciais inválidas"}))

        resposta = self.client.post(reverse("login"), {"username": "lurdes@email.com", "password": "errada1"})

        self.assertContains(resposta, "E-mail ou senha incorretos.")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_login_com_api_fora_do_ar_informa_indisponibilidade(self) -> None:
        self.usar_api(_falha_de_conexao)

        resposta = self.client.post(reverse("login"), {"username": "lurdes@email.com", "password": "senha123"})

        self.assertContains(resposta, "indisponível no momento")


class ChatViewTests(ApiFalsaMixin, TestCase):
    def test_pagina_exige_login(self) -> None:
        resposta = self.client.get(reverse("chat"))

        self.assertRedirects(resposta, f"{reverse('login')}?next=/", fetch_redirect_response=False)

    def test_requisicao_htmx_sem_login_recebe_hx_redirect(self) -> None:
        resposta = self.client.post(reverse("chat"), {"message": "oi"}, **HTMX)

        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta["HX-Redirect"], f"{reverse('login')}?next=/")

    def test_mensagem_htmx_e_encaminhada_a_api_e_renderiza_fragmento(self) -> None:
        self.autenticar()
        requisicoes = self.usar_api(lambda _: httpx.Response(200, json=RESPOSTA_CHAT))

        resposta = self.client.post(reverse("chat"), {"message": "queria marca consulta pra semana q vem"}, **HTMX)

        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "assistant/partials/mensagem_item.html")
        self.assertContains(resposta, "queria marca consulta pra semana q vem")
        self.assertContains(resposta, "Achei um horário com o médico do coração.<br>1. Para marcar, escreva SIM.")
        enviado = requisicoes[0]
        self.assertEqual((enviado.method, enviado.url.path), ("POST", "/api/assistant/chat"))
        self.assertEqual(enviado.headers["Authorization"], "Bearer jwt-valido")
        self.assertEqual(json.loads(enviado.content), {"mensagem": "queria marca consulta pra semana q vem", "contexto": {}})
        self.assertEqual(self.client.session[SessaoAssistente.CONTEXTO], RESPOSTA_CHAT["contexto"])

    def test_contexto_da_conversa_e_reenviado_na_mensagem_seguinte(self) -> None:
        self.autenticar()
        requisicoes = self.usar_api(lambda _: httpx.Response(200, json=RESPOSTA_CHAT))

        self.client.post(reverse("chat"), {"message": "quero marcar cardiologista"}, **HTMX)
        self.client.post(reverse("chat"), {"message": "sim"}, **HTMX)

        self.assertEqual(json.loads(requisicoes[1].content)["contexto"], RESPOSTA_CHAT["contexto"])

    def test_mensagem_do_paciente_e_escapada_no_html(self) -> None:
        self.autenticar()
        self.usar_api(lambda _: httpx.Response(200, json=RESPOSTA_CHAT))

        resposta = self.client.post(reverse("chat"), {"message": "<script>alert(1)</script>"}, **HTMX)

        self.assertNotContains(resposta, "<script>alert(1)</script>")
        self.assertContains(resposta, "&lt;script&gt;")

    def test_api_indisponivel_exibe_mensagem_amigavel(self) -> None:
        self.autenticar()
        self.usar_api(_falha_de_conexao)

        resposta = self.client.post(reverse("chat"), {"message": "oi"}, **HTMX)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Não consegui falar com o sistema de agendamento agora.")

    def test_token_expirado_na_api_encerra_sessao(self) -> None:
        self.autenticar()
        self.usar_api(lambda _: httpx.Response(401, json={"detail": "Token inválido ou expirado"}))

        resposta = self.client.post(reverse("chat"), {"message": "oi"}, **HTMX)

        self.assertEqual(resposta.status_code, 401)
        self.assertEqual(resposta["HX-Redirect"], f"{reverse('login')}?next=/")
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_mensagem_vazia_nao_chama_a_api(self) -> None:
        self.autenticar()
        requisicoes = self.usar_api(lambda _: httpx.Response(200, json=RESPOSTA_CHAT))

        resposta = self.client.post(reverse("chat"), {"message": "   "}, **HTMX)

        self.assertEqual(resposta.status_code, 204)
        self.assertEqual(requisicoes, [])


class CalendarioViewTests(ApiFalsaMixin, TestCase):
    def test_lista_consultas_do_paciente_vindas_da_api(self) -> None:
        self.autenticar()
        consultas = [
            {"id": 1, "status": "agendada", "data": "2027-10-25", "hora_inicio": "14:00", "hora_fim": "14:30",
             "medico_id": 2, "medico_nome": "Dra. Maria Silva", "especialidade": "Clínica Geral", "observacao": None},
            {"id": 2, "status": "cancelada", "data": "2026-11-10", "hora_inicio": "09:00", "hora_fim": "09:30",
             "medico_id": 1, "medico_nome": "Dr. João Mendes", "especialidade": "Cardiologia", "observacao": None},
        ]
        requisicoes = self.usar_api(lambda _: httpx.Response(200, json=consultas))

        resposta = self.client.get(reverse("calendario"))

        self.assertContains(resposta, "25/10/2027")
        self.assertContains(resposta, "segunda-feira")
        self.assertContains(resposta, "Dra. Maria Silva")
        self.assertEqual([c.id for c in resposta.context["proximas"]], [1])
        self.assertEqual([c.id for c in resposta.context["historico"]], [2])
        self.assertEqual(requisicoes[0].url.path, "/api/consultas/minhas")

    def test_paciente_sem_cadastro_recebe_orientacao(self) -> None:
        self.autenticar()
        self.usar_api(lambda _: httpx.Response(404, json={"detail": "Nenhum paciente vinculado ao usuário autenticado"}))

        resposta = self.client.get(reverse("calendario"))

        self.assertContains(resposta, "Seu cadastro de paciente não foi encontrado.")
