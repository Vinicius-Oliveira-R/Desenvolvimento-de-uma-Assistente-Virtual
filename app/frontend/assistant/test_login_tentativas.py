"""Login: 429 tem mensagem própria, sem novas tentativas automáticas e sem confundir com indisponibilidade."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
from django.contrib.auth import SESSION_KEY
from django.test import TestCase
from django.urls import reverse

from assistant.tests import ApiFalsaMixin

CREDENCIAIS = {"username": "lurdes@email.com", "password": "senha-de-teste"}
SEM_PRAZO = "Muitas tentativas de entrada. Aguarde alguns minutos antes de tentar novamente."


class LoginComMuitasTentativasTests(ApiFalsaMixin, TestCase):
    def _entrar(self, cabecalhos: dict[str, str]):
        requisicoes = self.usar_api(lambda _: httpx.Response(429, headers=cabecalhos, json={"detail": "Muitas tentativas"}))
        with self.assertLogs("assistant.login", level="WARNING") as logs:
            resposta = self.client.post(reverse("login"), CREDENCIAIS)
        self.assertIn("status=429", " ".join(logs.output))
        self.assertEqual(len(requisicoes), 1, "o front-end não pode repetir a autenticação sozinho")
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotContains(resposta, "indisponível")
        return resposta

    def test_retry_after_em_segundos_vira_prazo_arredondado(self) -> None:
        casos = {"180": "3 minutos", "61": "2 minutos", "30": "1 minuto", "60": "1 minuto", "3600": "1 hora"}
        for valor, prazo in casos.items():
            with self.subTest(retry_after=valor):
                resposta = self._entrar({"Retry-After": valor})
                self.assertContains(resposta, f"Muitas tentativas de entrada. Tente novamente em {prazo}.")

    def test_retry_after_como_data_http(self) -> None:
        daqui_a_pouco = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=100), usegmt=True)

        resposta = self._entrar({"Retry-After": daqui_a_pouco})

        self.assertContains(resposta, "Tente novamente em 2 minutos.")

    def test_retry_after_ausente_ou_invalido_nao_inventa_prazo(self) -> None:
        for cabecalhos in ({}, {"Retry-After": "amanha"}, {"Retry-After": "-5"}, {"Retry-After": "0"},
                           {"Retry-After": "99999999"}, {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}):
            with self.subTest(cabecalhos=cabecalhos):
                resposta = self._entrar(cabecalhos)
                self.assertContains(resposta, SEM_PRAZO)
                self.assertNotContains(resposta, "Tente novamente em")

    def test_credenciais_incorretas_e_falha_de_conexao_continuam_distintas(self) -> None:
        self.usar_api(lambda _: httpx.Response(401, json={"detail": "Credenciais inválidas"}))
        self.assertContains(self.client.post(reverse("login"), CREDENCIAIS), "E-mail ou senha incorretos.")

        def sem_conexao(requisicao: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusada", request=requisicao)

        self.usar_api(sem_conexao)
        with self.assertLogs("assistant.login", level="WARNING"):
            resposta = self.client.post(reverse("login"), CREDENCIAIS)
        self.assertContains(resposta, "indisponível no momento")
        self.assertNotContains(resposta, "Muitas tentativas")
