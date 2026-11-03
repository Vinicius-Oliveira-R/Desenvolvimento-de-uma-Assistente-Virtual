from django.conf import settings
from django.contrib.auth.views import LoginView
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.views.generic import TemplateView

from assistant.api_client import ApiError, RespostaAssistente, SessaoExpiradaError
from assistant.forms import LoginForm, MensagemForm
from assistant.mixins import ClinicaApiMixin
from assistant.session import SessaoAssistente


class PacienteLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form: LoginForm) -> HttpResponse:
        resposta = super().form_valid(form)
        SessaoAssistente.iniciar(self.request.session, form.get_user().api_token)
        return resposta


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
        token = await sessao.token()
        if not token:
            return await self.end_session(request)

        mensagem = form.cleaned_data["message"]
        try:
            resposta = await self.get_api_client().send_message(token, mensagem, await sessao.contexto())
        except SessaoExpiradaError:
            return await self.end_session(request)
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
        token = await SessaoAssistente(request.session).token()
        if not token:
            return await self.end_session(request)

        consultas, erro = [], None
        try:
            consultas = await self.get_api_client().list_my_appointments(token)
        except SessaoExpiradaError:
            return await self.end_session(request)
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
