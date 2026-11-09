from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import AbstractBaseUser
from django.http import HttpRequest

from assistant.api_client import ClinicaApiClient, CredenciaisInvalidasError


class FastAPIAuthBackend(BaseBackend):
    """Autentica na API FastAPI (fonte da verdade dos usuários) e espelha o usuário no Django."""

    def authenticate(
        self, request: HttpRequest | None, username: str | None = None, password: str | None = None, **kwargs
    ) -> AbstractBaseUser | None:
        if not username or not password:
            return None
        try:
            sessao = ClinicaApiClient.from_settings().authenticate(username, password)
        except CredenciaisInvalidasError:
            return None

        usuario, criado = get_user_model().objects.update_or_create(
            username=sessao.email, defaults={"email": sessao.email, "first_name": sessao.nome[:150]}
        )
        if criado:
            usuario.set_unusable_password()
            usuario.save(update_fields=["password"])
        usuario.api_token = sessao.token
        usuario.api_papel = sessao.papel
        return usuario

    def get_user(self, user_id: int) -> AbstractBaseUser | None:
        return get_user_model().objects.filter(pk=user_id).first()
