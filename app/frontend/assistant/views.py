import asyncio
from collections.abc import Mapping
from datetime import date

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

from assistant.api_client import ApiError, HorarioLivre, PermissaoNegadaError, RespostaAssistente
from assistant.forms import (
    MANTER_HORARIO,
    AgendamentoForm,
    AlteracaoConsultaForm,
    CadastroUsuarioForm,
    CancelamentoForm,
    FiltroConsultasForm,
    LoginForm,
    MensagemForm,
    opcoes_de_horario,
)
from assistant.mixins import ClinicaApiMixin
from assistant.perfis import EQUIPE, EQUIPE_CLINICA, PACIENTE, ROTULOS, pagina_inicial
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

    def get_default_redirect_url(self) -> str:
        return pagina_inicial(getattr(self.request.user, "api_papel", PACIENTE))


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


class EditarConsultaView(GestaoConsultasMixin, TemplateView):
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

        inicial = {
            "medico_id": consulta.medico_id,
            "data": consulta.data,
            "status": consulta.status if consulta.status != "cancelada" else "agendada",
            "observacao": consulta.observacao or "",
        }
        form = AlteracaoConsultaForm(
            dados,
            initial=inicial,
            medicos=medicos,
            horarios=horarios,
            url_horarios=f"{reverse('horarios_livres')}?modo=remarcar",
        )
        if dados is not None and form.is_valid():
            try:
                await cliente.update_appointment(self.token, consulta_id, form.dados_para_api())
            except ApiError as exc:
                form.add_error(None, exc.mensagem)
            else:
                messages.success(request, "Consulta atualizada.")
                return redirect("consultas")
        contexto = self.get_context_data(consulta=consulta, form=form, cancelamento=CancelamentoForm())
        return self.render_to_response(contexto)


class CancelarConsultaView(GestaoConsultasMixin, View):
    async def post(self, request: HttpRequest, consulta_id: int, *args, **kwargs) -> HttpResponse:
        if not CancelamentoForm(request.POST).is_valid():
            messages.error(request, "Marque a confirmação do paciente para cancelar a consulta.")
            return redirect("editar_consulta", consulta_id=consulta_id)
        try:
            await self.get_api_client().cancel_appointment(self.token, consulta_id)
        except ApiError as exc:
            messages.error(request, exc.mensagem)
            return redirect("editar_consulta", consulta_id=consulta_id)
        messages.success(request, "Consulta cancelada. O horário foi liberado.")
        return redirect("consultas")


class HorariosLivresView(GestaoConsultasMixin, View):
    async def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        escolha = _medico_e_data(request.GET)
        remarcando = request.GET.get("modo") == "remarcar"
        try:
            horarios = await self.horarios_livres(escolha)
        except ApiError:
            horarios = []
        if remarcando:
            vazio = MANTER_HORARIO
        elif escolha is None:
            vazio = "Escolha o médico e a data"
        else:
            vazio = "Selecione" if horarios else "Nenhum horário livre nesse dia"
        contexto = {"opcoes": opcoes_de_horario(horarios, vazio)}
        return TemplateResponse(request, "equipe/partials/opcoes_horario.html", contexto)
