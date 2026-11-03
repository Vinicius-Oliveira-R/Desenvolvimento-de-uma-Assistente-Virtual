from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from assistant.api_client import ApiError


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="E-mail", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "E-mail ou senha incorretos.",
        "api_indisponivel": "O sistema de agendamento está indisponível no momento. Tente novamente em instantes.",
    }

    def clean(self):
        try:
            return super().clean()
        except ApiError as exc:
            raise ValidationError(self.error_messages["api_indisponivel"], code="api_indisponivel") from exc


class MensagemForm(forms.Form):
    message = forms.CharField(max_length=500, strip=True)
