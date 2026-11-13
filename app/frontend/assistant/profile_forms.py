import re

from django import forms
from django.core.exceptions import ValidationError


class ContatoPacienteForm(forms.Form):
    email = forms.EmailField(label="E-mail")
    telefone = forms.CharField(label="Telefone com DDD", max_length=25)

    def clean_telefone(self):
        value = self.cleaned_data["telefone"]
        if re.search(r"[^0-9+()\-\s]", value):
            raise ValidationError("Telefone inválido")
        digits = re.sub(r"[^0-9]", "", value)
        if not 10 <= len(digits) <= 15:
            raise ValidationError("Informe entre 10 e 15 dígitos, com DDD")
        return digits
