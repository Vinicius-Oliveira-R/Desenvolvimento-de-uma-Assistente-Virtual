"""Tela do paciente com a API simulada: retomada, botões, falhas de conexão e ausência de rótulos."""
import json

import httpx
from django.test import TestCase, override_settings
from django.urls import reverse

from assistant.session import SessaoAssistente
from assistant.tests import HTMX, RESPOSTA_ABERTURA, ApiFalsaMixin

PROPOSTA = {
    "tipo": "agendar", "proposta": "Pr0posta-A", "horario_id": 7, "horarios_oferecidos": [7, 8],
    "confirmacao_pendente": True,
}
RESPOSTA_PROPOSTA = {
    "resposta": "Horário livre com o clínico geral:\nterça-feira, 10 de novembro, às 9 horas, com Dra. Maria Silva.",
    "estilo": "passo_a_passo",
    "intencao": "retomada",
    "resultado": "sugestao_horario",
    "opcoes": [
        {"codigo": "confirmar_horario", "rotulo": "Confirmar horário", "proposta": "Pr0posta-A", "valor": None},
        {"codigo": "outro_horario", "rotulo": "Ver outro horário", "proposta": "Pr0posta-A", "valor": None},
    ],
    "contexto": {"acao_pendente": PROPOSTA, "estilo": "passo_a_passo"},
}


class ChatInterfaceTests(ApiFalsaMixin, TestCase):
    def setUp(self) -> None:
        self.autenticar()

    def _salvar_contexto(self, contexto: dict) -> None:
        sessao = self.client.session
        sessao[SessaoAssistente.CONTEXTO] = contexto
        sessao.save()

    def test_atualizar_a_pagina_reapresenta_a_etapa_guardada_na_sessao(self) -> None:
        self._salvar_contexto(RESPOSTA_PROPOSTA["contexto"])
        requisicoes = self.usar_api(lambda _: httpx.Response(200, json=RESPOSTA_PROPOSTA))

        resposta = self.client.get(reverse("chat"))

        enviado = requisicoes[0]
        self.assertEqual((enviado.method, enviado.url.path), ("POST", "/api/assistant/retomar"))
        self.assertEqual(json.loads(enviado.content), {"contexto": RESPOSTA_PROPOSTA["contexto"]})
        self.assertContains(resposta, "terça-feira, 10 de novembro, às 9 horas")
        self.assertContains(resposta, ">Confirmar horário</button>", html=False)
        self.assertContains(resposta, 'name="proposta" value="Pr0posta-A"')
        self.assertNotContains(resposta, "Como posso ajudar com o seu agendamento hoje?")

    def test_sem_api_a_abertura_mostra_as_tres_operacoes(self) -> None:
        def sem_conexao(requisicao: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusada", request=requisicao)

        self.usar_api(sem_conexao)

        resposta = self.client.get(reverse("chat"))

        for rotulo in ("Marcar consulta", "Minhas consultas", "Mudar ou cancelar"):
            self.assertContains(resposta, f">{rotulo}</button>", html=False)

    def test_botao_envia_codigo_proposta_e_valor_para_a_api(self) -> None:
        requisicoes = self.usar_api(lambda _: httpx.Response(200, json=RESPOSTA_PROPOSTA))
        campos = {"message": "2. Às 14h", "acao": "escolher", "proposta": "Pr0posta-A", "valor": "2"}

        resposta = self.client.post(reverse("chat"), campos, **HTMX)

        corpo = json.loads(requisicoes[0].content)
        self.assertEqual(corpo["mensagem"], "2. Às 14h")
        self.assertEqual(corpo["acao"], {"codigo": "escolher", "proposta": "Pr0posta-A", "valor": "2"})
        self.assertContains(resposta, "2. Às 14h")

    def test_botao_com_codigo_desconhecido_nao_chega_a_api(self) -> None:
        requisicoes = self.usar_api(lambda _: httpx.Response(200, json=RESPOSTA_PROPOSTA))

        resposta = self.client.post(reverse("chat"), {"message": "x", "acao": "apagar_tudo"}, **HTMX)

        self.assertEqual(resposta.status_code, 204)
        self.assertEqual(requisicoes, [])

    def test_conexao_que_cai_depois_da_confirmacao_orienta_a_conferir(self) -> None:
        self._salvar_contexto(RESPOSTA_PROPOSTA["contexto"])
        falhas = {
            "tempo esgotado": lambda requisicao: (_ for _ in ()).throw(httpx.ReadTimeout("lenta", request=requisicao)),
            "erro 502": lambda _: httpx.Response(502, text="Bad gateway"),
        }
        for nome, falha in falhas.items():
            with self.subTest(falha=nome):
                self.usar_api(falha)
                campos = {"message": "Confirmar horário", "acao": "confirmar_horario", "proposta": "Pr0posta-A"}

                resposta = self.client.post(reverse("chat"), campos, **HTMX)

                self.assertContains(resposta, "não sei se o seu pedido foi registrado")
                self.assertContains(resposta, "Antes de repetir, confira em Minhas consultas.")
                self.assertContains(resposta, f'href="{reverse("calendario")}"')
                self.assertNotContains(resposta, "Sua consulta está marcada")
                self.assertEqual(self.client.session[SessaoAssistente.CONTEXTO], RESPOSTA_PROPOSTA["contexto"])

    def test_sem_conexao_antes_do_envio_garante_que_nada_mudou(self) -> None:
        self._salvar_contexto(RESPOSTA_PROPOSTA["contexto"])

        def sem_conexao(requisicao: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusada", request=requisicao)

        self.usar_api(sem_conexao)

        resposta = self.client.post(reverse("chat"), {"message": "sim"}, **HTMX)

        self.assertContains(resposta, "Nada foi alterado.")
        self.assertNotContains(resposta, "não sei se o seu pedido foi registrado")

    def test_tempo_esgotado_sem_confirmacao_pendente_nao_assusta(self) -> None:
        self.usar_api(lambda requisicao: (_ for _ in ()).throw(httpx.ReadTimeout("lenta", request=requisicao)))

        resposta = self.client.post(reverse("chat"), {"message": "quais dias tem?"}, **HTMX)

        self.assertContains(resposta, "Não consegui falar com o sistema de agendamento agora.")
        self.assertNotContains(resposta, "não sei se o seu pedido foi registrado")

    def test_novo_agendamento_encerra_a_proposta_e_inicia_outra_busca(self) -> None:
        self._salvar_contexto({**RESPOSTA_PROPOSTA["contexto"], "preferencia_estilo": "padrao"})
        nova = {**RESPOSTA_PROPOSTA, "resposta": "Horários livres com o clínico geral:", "contexto": {"acao_pendente": None}}
        requisicoes = self.usar_api(lambda _: httpx.Response(200, json=nova))

        redirecionamento = self.client.post(reverse("novo_agendamento"))
        pagina = self.client.get(reverse("chat"))
        recarregada = self.client.get(reverse("chat"))

        self.assertRedirects(redirecionamento, reverse("chat"), fetch_redirect_response=False)
        corpo = json.loads(requisicoes[0].content)
        self.assertIsNone(corpo["contexto"]["acao_pendente"])
        self.assertEqual(corpo["contexto"]["preferencia_estilo"], "padrao")
        self.assertEqual(corpo["acao"], {"codigo": "marcar_consulta"})
        self.assertContains(pagina, "Novo agendamento")
        self.assertContains(pagina, "Horários livres com o clínico geral:")
        self.assertEqual([r.url.path for r in requisicoes], ["/api/assistant/chat", "/api/assistant/retomar"])
        self.assertEqual(recarregada.status_code, 200)

    @override_settings(ASSISTENTE_EXIBIR_DIAGNOSTICO=True)
    def test_diagnostico_tecnico_nao_mostra_rotulo_etario_nem_probabilidade(self) -> None:
        # Mesmo uma API antiga que ainda devolvesse o perfil não faz o rótulo chegar à tela.
        legado = {**RESPOSTA_PROPOSTA, "perfil": "IDOSO", "probabilidade_idoso": 0.97, "heuristicas": {"vagueza": 1.0}}
        self.usar_api(lambda _: httpx.Response(200, json=legado))

        resposta = self.client.post(reverse("chat"), {"message": "quero marcar"}, **HTMX)

        self.assertContains(resposta, "Intenção: retomada · Resultado: sugestao_horario")
        for proibido in ("IDOSO", "PADRAO", "Perfil", "0.97", "probabilidade", "vagueza"):
            self.assertNotContains(resposta, proibido)

    def test_tela_tem_rotulo_acessivel_anuncio_e_menu_que_nao_cobre_o_chat(self) -> None:
        self.usar_api(lambda _: httpx.Response(200, json=RESPOSTA_ABERTURA))

        resposta = self.client.get(reverse("chat"))

        self.assertContains(resposta, '<label for="mensagem" class="visually-hidden">', html=False)
        self.assertContains(resposta, 'id="anuncio" class="visually-hidden" role="status" aria-live="polite"')
        self.assertContains(resposta, 'aria-label="Conversa com o assistente"')
        self.assertContains(resposta, 'aria-controls="menu-lateral"')
        self.assertContains(resposta, f'action="{reverse("novo_agendamento")}"')
        self.assertContains(resposta, ">Minhas consultas", html=False)
        self.assertNotContains(resposta, "Meus Agendamentos")
