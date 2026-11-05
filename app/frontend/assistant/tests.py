import json
from collections.abc import Callable
from datetime import timedelta
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

        self.assertRedirects(resposta, reverse("inicio"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("inicio")), reverse("chat"), fetch_redirect_response=False)
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

        self.assertRedirects(resposta, reverse("inicio"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("inicio")), reverse("equipe"), fetch_redirect_response=False)
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








class PainelPorPapelTests(ApiFalsaMixin, TestCase):
    def test_inicio_leva_cada_papel_a_sua_area(self) -> None:
        destinos = {"paciente": "chat", "medico": "agenda_medica", "admin": "equipe", "gestor": "equipe"}
        self.autenticar()
        for papel, destino in destinos.items():
            sessao = self.client.session
            sessao[SessaoAssistente.PAPEL] = papel
            sessao.save()

            resposta = self.client.get(reverse("inicio"))

            self.assertRedirects(resposta, reverse(destino), fetch_redirect_response=False, msg_prefix=papel)

    def test_agenda_do_medico_mostra_somente_as_consultas_dele_no_dia(self) -> None:
        self.autenticar(papel="medico")
        perfil = {**PERFIL_ATENDENTE, "papel": "medico", "medico_id": 3}
        requisicoes = self.usar_api(_api_da_equipe({"GET /api/auth/me": (200, perfil), **API_DA_AGENDA}))

        resposta = self.client.get(reverse("agenda_medica"), {"data": "2026-11-10"})

        self.assertContains(resposta, "Lurdes Andrade")
        self.assertContains(resposta, reverse("editar_consulta", args=[5]))
        agenda = next(r for r in requisicoes if r.url.path == "/api/consultas")
        self.assertEqual(
            dict(agenda.url.params), {"medico_id": "3", "data_inicio": "2026-11-10", "data_fim": "2026-11-10"}
        )

    def test_medico_sem_ficha_vinculada_e_orientado(self) -> None:
        self.autenticar(papel="medico")
        sem_ficha = {**PERFIL_ATENDENTE, "papel": "medico"}
        requisicoes = self.usar_api(_api_da_equipe({"GET /api/auth/me": (200, sem_ficha)}))

        resposta = self.client.get(reverse("agenda_medica"))

        self.assertContains(resposta, "Sua conta ainda não está vinculada a uma ficha de médico")
        self.assertFalse(any(r.url.path == "/api/consultas" for r in requisicoes))

    def test_atendente_nao_abre_a_agenda_pessoal_do_medico(self) -> None:
        self.autenticar(papel="admin")

        resposta = self.client.get(reverse("agenda_medica"))

        self.assertRedirects(resposta, reverse("equipe"), fetch_redirect_response=False)

    def test_liberacao_de_horarios_envia_o_pedido_a_api(self) -> None:
        self.autenticar(papel="admin")
        requisicoes = self.usar_api(
            _api_da_equipe({**API_DA_AGENDA, "POST /api/horarios/lote": (201, {"criados": 20, "ja_existentes": 4})})
        )
        amanha = timezone.localdate() + timedelta(days=1)

        resposta = self.client.post(
            reverse("liberar_horarios"),
            {
                "medico_id": "3", "data_inicio": amanha.isoformat(),
                "data_fim": (amanha + timedelta(days=6)).isoformat(),
                "dias_semana": ["0", "2"], "hora_inicio": "08:00", "hora_fim": "10:00", "duracao_minutos": "30",
            },
            follow=True,
        )

        self.assertContains(resposta, "20 horários liberados. 4 já existiam e foram mantidos.")
        pedido = json.loads(next(r for r in requisicoes if r.url.path == "/api/horarios/lote").content)
        self.assertEqual(pedido["dias_semana"], [0, 2])
        self.assertEqual((pedido["medico_id"], pedido["hora_inicio"], pedido["hora_fim"]), (3, "08:00", "10:00"))

    def test_liberacao_em_data_passada_e_barrada_antes_da_api(self) -> None:
        self.autenticar(papel="admin")
        requisicoes = self.usar_api(_api_da_equipe(API_DA_AGENDA))
        ontem = timezone.localdate() - timedelta(days=1)

        resposta = self.client.post(
            reverse("liberar_horarios"),
            {
                "medico_id": "3", "data_inicio": ontem.isoformat(), "data_fim": ontem.isoformat(),
                "dias_semana": ["0"], "hora_inicio": "08:00", "hora_fim": "10:00", "duracao_minutos": "30",
            },
        )

        self.assertContains(resposta, "Escolha hoje ou uma data futura.")
        self.assertFalse(any(r.url.path == "/api/horarios/lote" for r in requisicoes))


REMARCACAO = {"medico_id": "3", "data": "2026-11-10", "horario_id": "8", "motivo": "Médico em congresso"}


class FluxoDeConfirmacaoTests(ApiFalsaMixin, TestCase):
    def usar_agenda(self, extras: dict[str, tuple[int, object]] | None = None) -> list[httpx.Request]:
        self.autenticar(papel="admin")
        return self.usar_api(_api_da_equipe({**API_DA_AGENDA, **(extras or {})}))

    @staticmethod
    def _enviados(requisicoes: list[httpx.Request], metodo: str, caminho: str) -> list[dict]:
        return [json.loads(r.content) for r in requisicoes if r.method == metodo and r.url.path == caminho]

    def test_remarcacao_pede_confirmacao_de_quem_solicita_antes_de_enviar(self) -> None:
        requisicoes = self.usar_agenda()

        resposta = self.client.post(reverse("editar_consulta", args=[5]), REMARCACAO)

        self.assertContains(resposta, "Tem certeza?")
        self.assertContains(resposta, "Pedir ao paciente para remarcar a consulta de Lurdes Andrade")
        self.assertContains(resposta, "10/11/2026 às 10:00 com Dr. João Mendes")
        self.assertContains(resposta, 'name="confirmar" value="1"')
        self.assertFalse([r for r in requisicoes if r.method != "GET"])

    def test_remarcacao_confirmada_vira_pedido_ao_paciente(self) -> None:
        requisicoes = self.usar_agenda({"POST /api/consultas/5/solicitacoes": (201, {"id": 1})})

        resposta = self.client.post(reverse("editar_consulta", args=[5]), {**REMARCACAO, "confirmar": "1"}, follow=True)

        self.assertContains(resposta, "Pedido de remarcação enviado ao paciente.")
        self.assertEqual(
            self._enviados(requisicoes, "POST", "/api/consultas/5/solicitacoes"),
            [{"tipo": "reagendamento", "horario_id": 8, "motivo": "Médico em congresso"}],
        )
        self.assertEqual(self._enviados(requisicoes, "PUT", "/api/consultas/5"), [])

    def test_paciente_que_ja_confirmou_permite_remarcar_na_hora(self) -> None:
        requisicoes = self.usar_agenda({"PUT /api/consultas/5": (200, {"id": 5})})

        self.client.post(
            reverse("editar_consulta", args=[5]), {**REMARCACAO, "aplicar_agora": "on", "confirmar": "1"}
        )

        enviados = self._enviados(requisicoes, "PUT", "/api/consultas/5")
        self.assertEqual(enviados, [{"horario_id": 8, "confirmado": True}])

    def test_remarcar_sem_escolher_o_novo_horario_e_barrado(self) -> None:
        requisicoes = self.usar_agenda()

        resposta = self.client.post(reverse("editar_consulta", args=[5]), {**REMARCACAO, "horario_id": ""})

        self.assertContains(resposta, "Este campo é obrigatório.")
        self.assertNotContains(resposta, "Tem certeza?")
        self.assertFalse([r for r in requisicoes if r.method != "GET"])

    def test_cancelamento_confirma_e_depois_envia_o_pedido(self) -> None:
        requisicoes = self.usar_agenda({"POST /api/consultas/5/solicitacoes": (201, {"id": 2})})

        confirmacao = self.client.post(reverse("cancelar_consulta", args=[5]), {"cancelamento-motivo": ""})
        self.assertContains(confirmacao, "Pedir ao paciente para cancelar a consulta de Lurdes Andrade")

        resposta = self.client.post(
            reverse("cancelar_consulta", args=[5]), {"cancelamento-motivo": "", "confirmar": "1"}, follow=True
        )

        self.assertContains(resposta, "Pedido de cancelamento enviado ao paciente.")
        self.assertEqual(
            self._enviados(requisicoes, "POST", "/api/consultas/5/solicitacoes"),
            [{"tipo": "cancelamento", "motivo": None}],
        )

    def test_cancelamento_imediato_usa_a_rota_direta(self) -> None:
        requisicoes = self.usar_agenda({"DELETE /api/consultas/5": (200, {"id": 5, "status": "cancelada"})})

        resposta = self.client.post(
            reverse("cancelar_consulta", args=[5]), {"cancelamento-aplicar_agora": "on", "confirmar": "1"}, follow=True
        )

        self.assertContains(resposta, "Consulta cancelada. O horário foi liberado e o paciente foi avisado.")
        self.assertEqual(self._enviados(requisicoes, "DELETE", "/api/consultas/5"), [{"confirmado": True}])

    def test_situacao_e_observacao_sao_salvas_sem_pedido_ao_paciente(self) -> None:
        requisicoes = self.usar_agenda({"PUT /api/consultas/5": (200, {"id": 5})})

        self.client.post(
            reverse("situacao_consulta", args=[5]),
            {"situacao-status": "realizada", "situacao-observacao": "Retorno em 30 dias"},
        )

        self.assertEqual(
            self._enviados(requisicoes, "PUT", "/api/consultas/5"),
            [{"status": "realizada", "observacao": "Retorno em 30 dias", "confirmado": True}],
        )

    def test_agenda_sinaliza_consulta_aguardando_o_paciente(self) -> None:
        pendente = {**CONSULTA, "solicitacao_pendente": "reagendamento_pendente"}
        self.usar_agenda({"GET /api/consultas": (200, [pendente]), "GET /api/consultas/5": (200, pendente)})

        self.assertContains(self.client.get(reverse("consultas")), "Aguardando paciente")
        self.assertContains(
            self.client.get(reverse("editar_consulta", args=[5])), "Aguardando o paciente responder ao pedido de"
        )


PEDIDO = {"id": 11, "consulta_id": 5, "tipo": "reagendamento_pendente", "status": "pendente", "criado_em": "x",
          "mensagem": "Recepção pediu para remarcar sua consulta com Dr. João Mendes.", "acao_necessaria": True}
AVISO = {"id": 12, "consulta_id": 5, "tipo": "aviso", "status": "pendente", "criado_em": "x",
         "mensagem": "Lurdes Andrade cancelou pelo assistente a consulta.", "acao_necessaria": False}


class NotificacoesTests(ApiFalsaMixin, TestCase):
    def test_modal_lista_pedidos_com_aceitar_e_recusar_e_avisos_com_ciente(self) -> None:
        self.autenticar()
        self.usar_api(_api_da_equipe({"GET /api/notificacoes": (200, [PEDIDO, AVISO])}))

        resposta = self.client.get(reverse("notificacoes_pendentes"), **HTMX)

        self.assertContains(resposta, "Recepção pediu para remarcar sua consulta")
        self.assertContains(resposta, "Aceitar")
        self.assertContains(resposta, "Recusar", count=1)
        self.assertContains(resposta, "Ciente")
        self.assertContains(resposta, reverse("responder_notificacao", args=[11]))

    def test_resposta_vai_para_a_api_e_o_contador_e_avisado(self) -> None:
        self.autenticar()
        requisicoes = self.usar_api(
            _api_da_equipe({"POST /api/notificacoes/11/responder": (200, {}), "GET /api/notificacoes": (200, [])})
        )

        resposta = self.client.post(reverse("responder_notificacao", args=[11]), {"aceitar": "nao"}, **HTMX)

        self.assertContains(resposta, "Pedido recusado.")
        self.assertEqual(resposta["HX-Trigger"], "notificacoes-atualizadas")
        enviado = next(r for r in requisicoes if r.method == "POST")
        self.assertEqual(json.loads(enviado.content), {"aceitar": False})

    def test_recusa_da_api_aparece_no_modal(self) -> None:
        self.autenticar()
        conflito = (409, {"detail": "O novo horário escolhido não está disponível"})
        rotas = {"POST /api/notificacoes/11/responder": conflito, "GET /api/notificacoes": (200, [PEDIDO])}
        self.usar_api(_api_da_equipe(rotas))

        resposta = self.client.post(reverse("responder_notificacao", args=[11]), {"aceitar": "sim"}, **HTMX)

        self.assertContains(resposta, "O novo horário escolhido não está disponível")

    def test_contador_mostra_quantas_notificacoes_estao_pendentes(self) -> None:
        self.autenticar(papel="medico")
        self.usar_api(_api_da_equipe({"GET /api/notificacoes": (200, [PEDIDO, AVISO])}))

        resposta = self.client.get(reverse("notificacoes_contagem"), **HTMX)

        self.assertContains(resposta, ">2</span>")

    def test_barra_lateral_tem_o_sino_de_notificacoes(self) -> None:
        self.autenticar()

        resposta = self.client.get(reverse("chat"))

        self.assertContains(resposta, reverse("notificacoes_pendentes"))
        self.assertContains(resposta, 'id="modal-notificacoes"')

