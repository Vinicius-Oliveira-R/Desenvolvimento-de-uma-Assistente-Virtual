import asyncio
from collections.abc import Mapping
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse, QueryDict
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from assistant.api_client import ApiError, ConsultaAgendada, HorarioLivre, PermissaoNegadaError, RespostaAssistente
from assistant.forms import (
    AgendamentoForm,
    CadastroUsuarioForm,
    CancelamentoForm,
    FiltroConsultasForm,
    LiberacaoHorariosForm,
    LoginForm,
    MensagemForm,
    RemarcacaoForm,
    SituacaoForm,
    opcoes_de_horario,
)
from assistant.mixins import ClinicaApiMixin
from assistant.perfis import EQUIPE, EQUIPE_CLINICA, MEDICO, ROTULOS, TODOS, pagina_inicial
from assistant.session import SessaoAssistente

API_INDISPONIVEL = "O sistema da clínica está indisponível no momento. Tente novamente em instantes."


def _medico_e_data(dados: Mapping[str, str]) -> tuple[int, date] | None:
    try:
        return int(dados["medico_id"]), date.fromisoformat(dados["data"])
    except (KeyError, TypeError, ValueError):
        return None


class ClinicaLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form: LoginForm) -> HttpResponse:
        resposta = super().form_valid(form)
        usuario = form.get_user()
        SessaoAssistente.iniciar(self.request.session, usuario.api_token, usuario.api_papel)
        return resposta


class DashboardRedirectView(ClinicaApiMixin, View):
    papeis_permitidos = TODOS

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return redirect(pagina_inicial(self.papel))


class ChatView(ClinicaApiMixin, TemplateView):
    template_name = "assistant/chat.html"
    partial_template_name = "assistant/partials/mensagem_item.html"
    resposta_api_indisponivel = (
        "Não consegui falar com o sistema de agendamento agora. Tente de novo em alguns instantes."
    )

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return self.render_to_response(self.get_context_data(**kwargs))

    async def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        form = MensagemForm(request.POST)
        if not form.is_valid():
            return HttpResponse(status=204)

        sessao = SessaoAssistente(request.session)
        mensagem = form.cleaned_data["message"]
        try:
            resposta = await self.get_api_client().send_message(self.token, mensagem, await sessao.contexto())
        except ApiError:
            return self._render_troca(mensagem, self.resposta_api_indisponivel)

        await sessao.salvar_contexto(resposta.contexto)
        return self._render_troca(mensagem, resposta.texto, resposta)

    def _render_troca(self, mensagem: str, texto: str, resposta: RespostaAssistente | None = None) -> TemplateResponse:
        contexto = {
            "user_message": mensagem,
            "bot_response": texto,
            "diagnostico": resposta if settings.ASSISTENTE_EXIBIR_DIAGNOSTICO else None,
        }
        return TemplateResponse(self.request, self.partial_template_name, contexto)


class CalendarioView(ClinicaApiMixin, TemplateView):
    template_name = "assistant/calendario.html"

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        consultas, erro = [], None
        try:
            consultas = await self.get_api_client().list_my_appointments(self.token)
        except ApiError as exc:
            erro = (
                "Seu cadastro de paciente não foi encontrado. Procure a recepção da clínica."
                if exc.status_code == 404
                else "Não foi possível carregar suas consultas agora. Tente novamente em instantes."
            )
        contexto = self.get_context_data(
            proximas=[consulta for consulta in consultas if consulta.ativa],
            historico=[consulta for consulta in consultas if not consulta.ativa],
            erro=erro,
            **kwargs,
        )
        return self.render_to_response(contexto)


class EquipeView(ClinicaApiMixin, TemplateView):
    template_name = "equipe/painel.html"
    papeis_permitidos = EQUIPE

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        pacientes, erro = None, None
        try:
            pacientes = await self.get_api_client().list_patients(self.token)
        except PermissaoNegadaError:
            pacientes = None
        except ApiError:
            erro = API_INDISPONIVEL
        return self.render_to_response(self.get_context_data(pacientes=pacientes, erro=erro, **kwargs))


class CadastroUsuarioView(ClinicaApiMixin, TemplateView):
    template_name = "equipe/cadastro.html"
    papeis_permitidos = EQUIPE

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return await self._atender(request, None)

    async def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return await self._atender(request, request.POST)

    async def _atender(self, request: HttpRequest, dados: QueryDict | None) -> HttpResponse:
        cliente = self.get_api_client()
        try:
            perfil, especialidades = await asyncio.gather(
                cliente.get_profile(self.token), cliente.list_specialties(self.token)
            )
        except ApiError:
            return self.render_to_response(self.get_context_data(erro=API_INDISPONIVEL))

        form = CadastroUsuarioForm(dados, papeis=perfil.papeis_cadastraveis, especialidades=especialidades)
        if dados is not None and form.is_valid():
            try:
                usuario = await cliente.register_user(self.token, form.dados_para_api())
            except ApiError as exc:
                form.add_error(None, exc.mensagem)
            else:
                messages.success(request, f"{usuario['nome']} foi cadastrado(a) como {ROTULOS[usuario['papel']]}.")
                return redirect("cadastro_usuario")
        return self.render_to_response(self.get_context_data(form=form))


class GestaoConsultasMixin(ClinicaApiMixin):
    papeis_permitidos = EQUIPE_CLINICA

    async def horarios_livres(self, escolha: tuple[int, date] | None) -> list[HorarioLivre]:
        return await self.get_api_client().list_free_slots(self.token, *escolha) if escolha else []


class ConsultasView(GestaoConsultasMixin, TemplateView):
    template_name = "equipe/consultas.html"

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        cliente = self.get_api_client()
        try:
            medicos = await cliente.list_doctors(self.token)
            filtro = FiltroConsultasForm(
                request.GET or {"data_inicio": timezone.localdate().isoformat()}, medicos=medicos
            )
            consultas = (
                await cliente.list_appointments(self.token, filtro.filtros_para_api()) if filtro.is_valid() else []
            )
        except ApiError:
            return self.render_to_response(self.get_context_data(erro=API_INDISPONIVEL))
        return self.render_to_response(self.get_context_data(filtro=filtro, consultas=consultas))


class NovaConsultaView(GestaoConsultasMixin, TemplateView):
    template_name = "equipe/consulta_nova.html"

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return await self._atender(request, None)

    async def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return await self._atender(request, request.POST)

    async def _atender(self, request: HttpRequest, dados: QueryDict | None) -> HttpResponse:
        cliente = self.get_api_client()
        try:
            pacientes, medicos, horarios = await asyncio.gather(
                cliente.list_patients(self.token),
                cliente.list_doctors(self.token),
                self.horarios_livres(_medico_e_data(dados or {})),
            )
        except ApiError:
            return self.render_to_response(self.get_context_data(erro=API_INDISPONIVEL))

        form = AgendamentoForm(
            dados, pacientes=pacientes, medicos=medicos, horarios=horarios, url_horarios=reverse("horarios_livres")
        )
        if dados is not None and form.is_valid():
            try:
                await cliente.create_appointment(self.token, form.dados_para_api())
            except ApiError as exc:
                form.add_error(None, exc.mensagem)
            else:
                messages.success(request, "Consulta agendada.")
                return redirect("consultas")
        return self.render_to_response(self.get_context_data(form=form))


class AcaoComConfirmacaoMixin:
    """Toda remarcação ou cancelamento passa por um "Tem certeza?" antes de ser enviado."""

    template_de_confirmacao = "equipe/confirmar_acao.html"

    def pedir_confirmacao(self, request: HttpRequest, consulta: ConsultaAgendada, resumo: str, aviso: str):
        campos = [
            (nome, valor)
            for nome, valores in request.POST.lists()
            if nome not in ("csrfmiddlewaretoken", "confirmar")
            for valor in valores
        ]
        contexto = {"consulta": consulta, "resumo": resumo, "aviso": aviso, "campos": campos, "acao": request.path}
        return TemplateResponse(request, self.template_de_confirmacao, contexto)


def _consulta_atual(consulta: ConsultaAgendada) -> str:
    quando = f"{consulta.data:%d/%m/%Y} às {consulta.hora_inicio}"
    return f"a consulta de {consulta.paciente_nome} com {consulta.medico_nome} de {quando}"


AVISO_DE_PEDIDO = "A consulta só muda quando o paciente aceitar. Ele recebe o pedido nas notificações e no chat."
AVISO_IMEDIATO = "A mudança vale agora e o paciente recebe um aviso."


def _aviso(aplicar_agora: bool) -> str:
    return AVISO_IMEDIATO if aplicar_agora else AVISO_DE_PEDIDO


class EditarConsultaView(AcaoComConfirmacaoMixin, GestaoConsultasMixin, TemplateView):
    template_name = "equipe/consulta_editar.html"

    async def get(self, request: HttpRequest, consulta_id: int, *args, **kwargs) -> HttpResponse:
        return await self._atender(request, consulta_id, None)

    async def post(self, request: HttpRequest, consulta_id: int, *args, **kwargs) -> HttpResponse:
        return await self._atender(request, consulta_id, request.POST)

    async def _atender(self, request: HttpRequest, consulta_id: int, dados: QueryDict | None) -> HttpResponse:
        cliente = self.get_api_client()
        try:
            consulta, medicos = await asyncio.gather(
                cliente.get_appointment(self.token, consulta_id), cliente.list_doctors(self.token)
            )
            escolha = _medico_e_data(dados) if dados is not None else (consulta.medico_id, consulta.data)
            horarios = await self.horarios_livres(escolha)
        except ApiError as exc:
            if exc.status_code == 404:
                messages.error(request, "Consulta não encontrada.")
                return redirect("consultas")
            return self.render_to_response(self.get_context_data(erro=API_INDISPONIVEL))

        remarcacao = RemarcacaoForm(
            dados,
            initial={"medico_id": consulta.medico_id, "data": consulta.data},
            medicos=medicos,
            horarios=horarios,
            url_horarios=reverse("horarios_livres"),
        )
        if dados is not None and remarcacao.is_valid():
            aplicar_agora = remarcacao.cleaned_data["aplicar_agora"]
            if "confirmar" not in dados:
                verbo = "Remarcar agora" if aplicar_agora else "Pedir ao paciente para remarcar"
                resumo = f"{verbo} {_consulta_atual(consulta)} para {remarcacao.destino()}?"
                return self.pedir_confirmacao(request, consulta, resumo, _aviso(aplicar_agora))
            try:
                if aplicar_agora:
                    await cliente.update_appointment(self.token, consulta_id, remarcacao.alteracao_direta())
                else:
                    await cliente.request_change(self.token, consulta_id, remarcacao.pedido_ao_paciente())
            except ApiError as exc:
                remarcacao.add_error(None, exc.mensagem)
            else:
                sucesso = "Consulta remarcada." if aplicar_agora else "Pedido de remarcação enviado ao paciente."
                messages.success(request, sucesso)
                return redirect("consultas")

        situacao = SituacaoForm(initial={"status": consulta.status, "observacao": consulta.observacao or ""})
        contexto = {"consulta": consulta, "form": remarcacao, "situacao": situacao, "cancelamento": CancelamentoForm()}
        return self.render_to_response(self.get_context_data(**contexto))


class SituacaoConsultaView(GestaoConsultasMixin, View):
    async def post(self, request: HttpRequest, consulta_id: int, *args, **kwargs) -> HttpResponse:
        form = SituacaoForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível salvar a situação da consulta.")
            return redirect("editar_consulta", consulta_id=consulta_id)
        try:
            await self.get_api_client().update_appointment(self.token, consulta_id, form.dados_para_api())
        except ApiError as exc:
            messages.error(request, exc.mensagem)
        else:
            messages.success(request, "Situação da consulta atualizada.")
        return redirect("editar_consulta", consulta_id=consulta_id)


class CancelarConsultaView(AcaoComConfirmacaoMixin, GestaoConsultasMixin, View):
    async def post(self, request: HttpRequest, consulta_id: int, *args, **kwargs) -> HttpResponse:
        form = CancelamentoForm(request.POST)
        cliente = self.get_api_client()
        if not form.is_valid():
            messages.error(request, "Revise o motivo do cancelamento.")
            return redirect("editar_consulta", consulta_id=consulta_id)
        aplicar_agora = form.cleaned_data["aplicar_agora"]
        try:
            if "confirmar" not in request.POST:
                consulta = await cliente.get_appointment(self.token, consulta_id)
                verbo = "Cancelar agora" if aplicar_agora else "Pedir ao paciente para cancelar"
                resumo = f"{verbo} {_consulta_atual(consulta)}?"
                return self.pedir_confirmacao(request, consulta, resumo, _aviso(aplicar_agora))
            if aplicar_agora:
                await cliente.cancel_appointment(self.token, consulta_id)
            else:
                await cliente.request_change(self.token, consulta_id, form.pedido_ao_paciente())
        except ApiError as exc:
            messages.error(request, exc.mensagem)
            return redirect("editar_consulta", consulta_id=consulta_id)
        if aplicar_agora:
            messages.success(request, "Consulta cancelada. O horário foi liberado e o paciente foi avisado.")
        else:
            messages.success(request, "Pedido de cancelamento enviado ao paciente.")
        return redirect("consultas")


class HorariosLivresView(GestaoConsultasMixin, View):
    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        escolha = _medico_e_data(request.GET)
        try:
            horarios = await self.horarios_livres(escolha)
        except ApiError:
            horarios = []
        if escolha is None:
            vazio = "Escolha o médico e a data"
        else:
            vazio = "Selecione" if horarios else "Nenhum horário livre nesse dia"
        contexto = {"opcoes": opcoes_de_horario(horarios, vazio)}
        return TemplateResponse(request, "equipe/partials/opcoes_horario.html", contexto)


class AgendaMedicaView(ClinicaApiMixin, TemplateView):
    template_name = "medico/agenda.html"
    papeis_permitidos = frozenset({MEDICO})

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        try:
            dia = date.fromisoformat(request.GET["data"])
        except (KeyError, ValueError):
            dia = timezone.localdate()

        cliente = self.get_api_client()
        try:
            perfil = await cliente.get_profile(self.token)
            filtros = {"medico_id": str(perfil.medico_id), "data_inicio": dia.isoformat(), "data_fim": dia.isoformat()}
            consultas = await cliente.list_appointments(self.token, filtros) if perfil.medico_id else []
        except ApiError:
            return self.render_to_response(self.get_context_data(erro=API_INDISPONIVEL, dia=dia))
        contexto = self.get_context_data(
            dia=dia,
            anterior=dia - timedelta(days=1),
            seguinte=dia + timedelta(days=1),
            e_hoje=dia == timezone.localdate(),
            consultas=consultas,
            sem_ficha=perfil.medico_id is None,
        )
        return self.render_to_response(contexto)


class LiberarHorariosView(ClinicaApiMixin, TemplateView):
    template_name = "equipe/horarios.html"
    papeis_permitidos = EQUIPE_CLINICA

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return await self._atender(request, None)

    async def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return await self._atender(request, request.POST)

    async def _atender(self, request: HttpRequest, dados: QueryDict | None) -> HttpResponse:
        cliente = self.get_api_client()
        try:
            medicos, perfil = await asyncio.gather(cliente.list_doctors(self.token), cliente.get_profile(self.token))
        except ApiError:
            return self.render_to_response(self.get_context_data(erro=API_INDISPONIVEL))

        form = LiberacaoHorariosForm(
            dados, medicos=medicos, medico_inicial=perfil.medico_id, hoje=timezone.localdate()
        )
        if dados is not None and form.is_valid():
            try:
                resultado = await cliente.release_slots(self.token, form.dados_para_api())
            except ApiError as exc:
                form.add_error(None, exc.mensagem)
            else:
                repetidos = resultado["ja_existentes"]
                aviso = f" {repetidos} já existiam e foram mantidos." if repetidos else ""
                messages.success(request, f"{resultado['criados']} horários liberados.{aviso}")
                return redirect("liberar_horarios")
        return self.render_to_response(self.get_context_data(form=form))


class NotificacoesView(ClinicaApiMixin, View):
    papeis_permitidos = TODOS
    template = "assistant/partials/notificacoes_modal.html"

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        return await self.listar(request)

    async def listar(self, request: HttpRequest, resultado: str | None = None, erro: str | None = None) -> HttpResponse:
        notificacoes = []
        try:
            notificacoes = await self.get_api_client().list_notifications(self.token)
        except ApiError:
            erro = erro or API_INDISPONIVEL
        contexto = {"notificacoes": notificacoes, "resultado": resultado, "erro": erro}
        resposta = TemplateResponse(request, self.template, contexto)
        resposta["HX-Trigger"] = "notificacoes-atualizadas"
        return resposta


class ResponderNotificacaoView(NotificacoesView):
    async def post(self, request: HttpRequest, notificacao_id: int, *args, **kwargs) -> HttpResponse:
        aceitar = request.POST.get("aceitar") == "sim"
        try:
            await self.get_api_client().respond_notification(self.token, notificacao_id, aceitar)
        except ApiError as exc:
            return await self.listar(request, erro=exc.mensagem)
        return await self.listar(request, resultado="Resposta registrada." if aceitar else "Pedido recusado.")


class ContagemNotificacoesView(ClinicaApiMixin, View):
    papeis_permitidos = TODOS

    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        try:
            total = len(await self.get_api_client().list_notifications(self.token))
        except ApiError:
            total = 0
        return TemplateResponse(request, "assistant/partials/contador_notificacoes.html", {"total": total})
