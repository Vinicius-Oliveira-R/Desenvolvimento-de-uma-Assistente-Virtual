from django.contrib.auth import alogout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from assistant.api_client import ClinicaApiClient, SessaoExpiradaError
from assistant.perfis import PACIENTE, pagina_inicial
from assistant.session import SessaoAssistente


class AsyncLoginRequiredMixin(LoginRequiredMixin):
    async def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not (await request.auser()).is_authenticated:
            return self.redirect_to_login_page(request)
        # Pula o dispatch síncrono do LoginRequiredMixin: ele leria request.user, uma consulta bloqueante ao banco.
        return await super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)

    def redirect_to_login_page(self, request: HttpRequest) -> HttpResponse:
        redirecionamento = redirect_to_login(request.get_full_path(), self.get_login_url(), self.get_redirect_field_name())
        if not request.headers.get("HX-Request"):
            return redirecionamento
        resposta = HttpResponse(status=401)
        resposta["HX-Redirect"] = redirecionamento.url
        return resposta


class ClinicaApiMixin(AsyncLoginRequiredMixin):
    papeis_permitidos: frozenset[str] = frozenset({PACIENTE})
    token: str
    papel: str

    async def dispatch(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if (await request.auser()).is_authenticated:
            sessao = SessaoAssistente(request.session)
            papel, token = await sessao.papel(), await sessao.token()
            if papel is None or token is None:
                return await self.end_session(request)
            if papel not in self.papeis_permitidos:
                return redirect(pagina_inicial(papel))
            self.token, self.papel = token, papel
        try:
            return await super().dispatch(request, *args, **kwargs)
        except SessaoExpiradaError:
            return await self.end_session(request)

    def get_api_client(self) -> ClinicaApiClient:
        return ClinicaApiClient.from_settings()

    async def end_session(self, request: HttpRequest) -> HttpResponse:
        await alogout(request)
        return self.redirect_to_login_page(request)
