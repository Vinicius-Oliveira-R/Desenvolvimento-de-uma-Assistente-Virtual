import json
from collections.abc import Callable
from unittest import mock

import httpx
from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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

    def autenticar(self, token: str = "jwt-valido", papel: str = "paciente") -> None:
        usuario = get_user_model().objects.create_user("lurdes@email.com", email="lurdes@email.com", first_name="Lurdes")
        self.client.force_login(usuario)
        sessao = self.client.session
        sessao[SessaoAssistente.TOKEN] = token
        sessao[SessaoAssistente.PAPEL] = papel
        sessao.save()


def _falha_de_conexao(requisicao: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("conexão recusada", request=requisicao)


class LoginTests(ApiFalsaMixin, TestCase):
    def test_login_autentica_na_api_e_guarda_token_na_sessao(self) -> None:
        requisicoes = self.usar_api(
            lambda _: httpx.Response(
                200,
                json={"id": 1, "nome": "Lurdes", "email": "lurdes@email.com", "papel": "paciente", "token": "jwt-abc"},
            )
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


PERFIL_ATENDENTE = {
    "id": 1,
    "nome": "Recepção",
    "email": "recepcao@email.com",
    "papel": "admin",
    "papeis_cadastraveis": ["admin", "paciente"],
}
CADASTRO_DE_PACIENTE = {
    "papel": "paciente",
    "nome": "Lurdes Andrade",
    "email": "lurdes.andrade@email.com",
    "senha": "senha123",
    "cpf": "123.456.789-00",
    "data_nascimento": "1948-05-12",
    "telefone": "(11) 99999-0000",
}


def _api_da_equipe(extras: dict[str, tuple[int, object]] | None = None) -> Callable[[httpx.Request], httpx.Response]:
    rotas = {
        "GET /api/auth/me": (200, PERFIL_ATENDENTE),
        "GET /api/medicos/especialidades": (200, ["Cardiologia", "Clínica Geral"]),
        **(extras or {}),
    }

    def responder(requisicao: httpx.Request) -> httpx.Response:
        status, corpo = rotas[f"{requisicao.method} {requisicao.url.path}"]
        return httpx.Response(status, json=corpo)

    return responder


class AreaDaEquipeTests(ApiFalsaMixin, TestCase):
    def test_login_da_equipe_leva_ao_painel(self) -> None:
        self.usar_api(
            lambda _: httpx.Response(200, json={**PERFIL_ATENDENTE, "token": "jwt-equipe"})
        )

        resposta = self.client.post(reverse("login"), {"username": "recepcao@email.com", "password": "senha123"})

        self.assertRedirects(resposta, reverse("equipe"), fetch_redirect_response=False)
        self.assertEqual(self.client.session[SessaoAssistente.PAPEL], "admin")

    def test_equipe_nao_usa_o_chat_e_paciente_nao_entra_no_painel(self) -> None:
        self.autenticar(papel="admin")
        self.assertRedirects(self.client.get(reverse("chat")), reverse("equipe"), fetch_redirect_response=False)

        sessao = self.client.session
        sessao[SessaoAssistente.PAPEL] = "paciente"
        sessao.save()
        self.assertRedirects(self.client.get(reverse("equipe")), reverse("chat"), fetch_redirect_response=False)

    def test_sessao_anterior_aos_perfis_pede_novo_login(self) -> None:
        self.autenticar()
        sessao = self.client.session
        del sessao[SessaoAssistente.PAPEL]
        sessao.save()

        resposta = self.client.get(reverse("chat"))

        self.assertRedirects(resposta, f"{reverse('login')}?next=/", fetch_redirect_response=False)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_formulario_oferece_somente_os_papeis_que_o_perfil_pode_cadastrar(self) -> None:
        self.autenticar(papel="admin")
        self.usar_api(_api_da_equipe())

        resposta = self.client.get(reverse("cadastro_usuario"))

        self.assertContains(resposta, '<option value="paciente"')
        self.assertContains(resposta, '<option value="admin"')
        self.assertNotContains(resposta, '<option value="medico"')
        self.assertContains(resposta, '<option value="Cardiologia"')

    def test_cadastro_de_paciente_envia_usuario_e_ficha_numa_unica_chamada(self) -> None:
        self.autenticar(papel="admin")
        criado = {"id": 9, "nome": "Lurdes Andrade", "email": "lurdes.andrade@email.com", "papel": "paciente"}
        requisicoes = self.usar_api(_api_da_equipe({"POST /api/auth/register": (201, criado)}))

        resposta = self.client.post(reverse("cadastro_usuario"), CADASTRO_DE_PACIENTE, follow=True)

        self.assertRedirects(resposta, reverse("cadastro_usuario"))
        self.assertContains(resposta, "Lurdes Andrade foi cadastrado(a) como Paciente.")
        cadastro = next(r for r in requisicoes if r.url.path == "/api/auth/register")
        self.assertEqual(
            json.loads(cadastro.content)["paciente"],
            {"cpf": "12345678900", "data_nascimento": "1948-05-12", "telefone": "11999990000"},
        )

    def test_ficha_incompleta_e_barrada_antes_de_chamar_a_api(self) -> None:
        self.autenticar(papel="admin")
        requisicoes = self.usar_api(_api_da_equipe())

        resposta = self.client.post(reverse("cadastro_usuario"), {**CADASTRO_DE_PACIENTE, "cpf": ""})

        self.assertContains(resposta, "Campo obrigatório para este tipo de usuário.")
        self.assertFalse(any(r.url.path == "/api/auth/register" for r in requisicoes))

    def test_recusa_da_api_aparece_no_formulario(self) -> None:
        self.autenticar(papel="admin")
        recusa = (409, {"detail": "Já existe um paciente com este CPF"})
        self.usar_api(_api_da_equipe({"POST /api/auth/register": recusa}))

        resposta = self.client.post(reverse("cadastro_usuario"), CADASTRO_DE_PACIENTE)

        self.assertContains(resposta, "Já existe um paciente com este CPF")

    def test_painel_lista_pacientes_para_quem_tem_acesso(self) -> None:
        self.autenticar(papel="admin")
        paciente = {
            "id": 1, "nome": "Lurdes Andrade", "cpf": "12345678900", "data_nascimento": "1948-05-12",
            "telefone": "11999990000",
        }
        self.usar_api(_api_da_equipe({"GET /api/pacientes": (200, [paciente])}))

        resposta = self.client.get(reverse("equipe"))

        self.assertContains(resposta, "123.456.789-00")
        self.assertContains(resposta, "12/05/1948")

    def test_painel_do_gestor_nao_exibe_dados_de_pacientes(self) -> None:
        self.autenticar(papel="gestor")
        self.usar_api(_api_da_equipe({"GET /api/pacientes": (403, {"detail": "Seu perfil não tem permissão"})}))

        resposta = self.client.get(reverse("equipe"))

        self.assertContains(resposta, "Seu perfil cadastra a equipe da clínica.")
        self.assertContains(resposta, "Gestor")


MEDICO = {"id": 3, "nome": "Dr. João Mendes", "crm": "CRM-SP-1", "especialidade": "Cardiologia"}
PACIENTE = {
    "id": 1, "usuario_id": 9, "nome": "Lurdes Andrade", "cpf": "12345678900",
    "data_nascimento": "1948-05-12", "telefone": "11999990000",
}
HORARIO_LIVRE = {
    "id": 8,
    "medico_id": 3,
    "data": "2026-11-10",
    "hora_inicio": "10:00",
    "hora_fim": "10:30",
    "disponivel": True,
}
CONSULTA = {
    "id": 5, "status": "agendada", "data": "2026-11-10", "hora_inicio": "09:00", "hora_fim": "09:30",
    "horario_id": 7, "medico_id": 3, "medico_nome": "Dr. João Mendes", "especialidade": "Cardiologia",
    "paciente_id": 1, "paciente_nome": "Lurdes Andrade", "observacao": None,
}
API_DA_AGENDA = {
    "GET /api/medicos": (200, [MEDICO]),
    "GET /api/pacientes": (200, [PACIENTE]),
    "GET /api/horarios": (200, [HORARIO_LIVRE]),
    "GET /api/consultas": (200, [CONSULTA]),
    "GET /api/consultas/5": (200, CONSULTA),
}


class GestaoDeConsultasTests(ApiFalsaMixin, TestCase):
    def usar_agenda(self, extras: dict[str, tuple[int, object]] | None = None) -> list[httpx.Request]:
        self.autenticar(papel="admin")
        return self.usar_api(_api_da_equipe({**API_DA_AGENDA, **(extras or {})}))

    @staticmethod
    def _corpo(requisicoes: list[httpx.Request], metodo: str, caminho: str) -> dict:
        return json.loads(next(r for r in requisicoes if r.method == metodo and r.url.path == caminho).content)

    def test_gestor_nao_gerencia_consultas(self) -> None:
        self.autenticar(papel="gestor")

        resposta = self.client.get(reverse("consultas"))

        self.assertRedirects(resposta, reverse("equipe"), fetch_redirect_response=False)

    def test_agenda_parte_de_hoje_e_repassa_os_filtros_a_api(self) -> None:
        requisicoes = self.usar_agenda()

        padrao = self.client.get(reverse("consultas"))
        filtrada = self.client.get(reverse("consultas"), {"medico_id": "3", "status": "agendada"})

        self.assertContains(padrao, "Lurdes Andrade")
        self.assertContains(padrao, reverse("editar_consulta", args=[5]))
        agendas = [r.url.params for r in requisicoes if r.url.path == "/api/consultas"]
        self.assertEqual(dict(agendas[0]), {"data_inicio": timezone.localdate().isoformat()})
        self.assertEqual(dict(agendas[1]), {"medico_id": "3", "status": "agendada"})
        self.assertContains(filtrada, "Lurdes Andrade")

    def test_horarios_livres_chegam_como_opcoes_via_htmx(self) -> None:
        requisicoes = self.usar_agenda()

        resposta = self.client.get(reverse("horarios_livres"), {"medico_id": "3", "data": "2026-11-10"}, **HTMX)

        self.assertContains(resposta, '<option value="8">10:00 às 10:30</option>')
        consulta_de_horarios = next(r for r in requisicoes if r.url.path == "/api/horarios")
        self.assertEqual(
            dict(consulta_de_horarios.url.params), {"medico_id": "3", "data": "2026-11-10", "disponivel": "true"}
        )

    def test_nova_consulta_e_enviada_para_a_api(self) -> None:
        requisicoes = self.usar_agenda({"POST /api/consultas": (201, {"id": 6})})

        resposta = self.client.post(
            reverse("nova_consulta"),
            {"paciente_id": "1", "medico_id": "3", "data": "2026-11-10", "horario_id": "8", "observacao": "Retorno"},
            follow=True,
        )

        self.assertRedirects(resposta, reverse("consultas"))
        self.assertContains(resposta, "Consulta agendada.")
        self.assertEqual(
            self._corpo(requisicoes, "POST", "/api/consultas"),
            {"paciente_id": 1, "medico_id": 3, "horario_id": 8, "data": "2026-11-10", "observacao": "Retorno"},
        )

    def test_horario_tomado_por_outro_paciente_aparece_no_formulario(self) -> None:
        recusa = (409, {"detail": "Este horário acabou de ser reservado por outro paciente."})
        self.usar_agenda({"POST /api/consultas": recusa})

        resposta = self.client.post(
            reverse("nova_consulta"), {"paciente_id": "1", "medico_id": "3", "data": "2026-11-10", "horario_id": "8"}
        )

        self.assertContains(resposta, "Este horário acabou de ser reservado por outro paciente.")

    def test_remarcacao_exige_confirmacao_do_paciente(self) -> None:
        requisicoes = self.usar_agenda()

        resposta = self.client.post(
            reverse("editar_consulta", args=[5]),
            {"medico_id": "3", "data": "2026-11-10", "horario_id": "8", "status": "agendada"},
        )

        self.assertContains(resposta, "Este campo é obrigatório.")
        self.assertFalse(any(r.method == "PUT" for r in requisicoes))

    def test_remarcacao_confirmada_envia_o_novo_horario(self) -> None:
        requisicoes = self.usar_agenda({"PUT /api/consultas/5": (200, {"id": 5})})

        resposta = self.client.post(
            reverse("editar_consulta", args=[5]),
            {"medico_id": "3", "data": "2026-11-10", "horario_id": "8", "status": "agendada", "confirmado": "on"},
        )

        self.assertRedirects(resposta, reverse("consultas"), fetch_redirect_response=False)
        self.assertEqual(
            self._corpo(requisicoes, "PUT", "/api/consultas/5"),
            {"status": "agendada", "observacao": "", "confirmado": True, "horario_id": 8},
        )

    def test_mudar_a_data_sem_escolher_horario_e_barrado(self) -> None:
        requisicoes = self.usar_agenda()

        resposta = self.client.post(
            reverse("editar_consulta", args=[5]),
            {"medico_id": "3", "data": "2026-11-12", "horario_id": "", "status": "agendada", "confirmado": "on"},
        )

        self.assertContains(resposta, "Para mudar o médico ou a data, escolha um novo horário.")
        self.assertFalse(any(r.method == "PUT" for r in requisicoes))

    def test_cancelamento_confirmado_libera_o_horario_pela_api(self) -> None:
        requisicoes = self.usar_agenda({"DELETE /api/consultas/5": (200, {"id": 5, "status": "cancelada"})})

        resposta = self.client.post(
            reverse("cancelar_consulta", args=[5]), {"cancelamento-confirmado": "on"}, follow=True
        )

        self.assertRedirects(resposta, reverse("consultas"))
        self.assertContains(resposta, "Consulta cancelada. O horário foi liberado.")
        self.assertEqual(self._corpo(requisicoes, "DELETE", "/api/consultas/5"), {"confirmado": True})

    def test_cancelamento_sem_confirmacao_nao_chama_a_api(self) -> None:
        requisicoes = self.usar_agenda()

        resposta = self.client.post(reverse("cancelar_consulta", args=[5]), {}, follow=True)

        self.assertRedirects(resposta, reverse("editar_consulta", args=[5]))
        self.assertContains(resposta, "Marque a confirmação do paciente para cancelar a consulta.")
        self.assertFalse(any(r.method == "DELETE" for r in requisicoes))
