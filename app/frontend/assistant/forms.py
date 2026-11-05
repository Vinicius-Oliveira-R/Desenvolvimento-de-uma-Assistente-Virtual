import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from assistant.api_client import ApiError, HorarioLivre, MedicoResumo, PacienteResumo
from assistant.perfis import PACIENTE, ROTULOS


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


class CadastroUsuarioForm(forms.Form):
    LIMITE_BYTES_SENHA = 72
    CAMPOS_DA_FICHA = {PACIENTE: ("cpf", "data_nascimento", "telefone"), "medico": ("crm", "especialidade")}

    papel = forms.ChoiceField(label="Tipo de usuário")
    nome = forms.CharField(label="Nome completo", min_length=2, max_length=150)
    email = forms.EmailField(label="E-mail")
    senha = forms.CharField(label="Senha inicial", min_length=6, widget=forms.PasswordInput)
    cpf = forms.CharField(label="CPF", required=False, widget=forms.TextInput(attrs={"inputmode": "numeric"}))
    data_nascimento = forms.DateField(
        label="Data de nascimento", required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    telefone = forms.CharField(
        label="Telefone com DDD", required=False, widget=forms.TextInput(attrs={"inputmode": "tel"})
    )
    crm = forms.CharField(label="CRM", required=False, max_length=30)
    especialidade = forms.ChoiceField(label="Especialidade", required=False)

    def __init__(self, *args, papeis: Sequence[str], especialidades: Sequence[str], **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["papel"].choices = [(papel, ROTULOS[papel]) for papel in papeis]
        self.fields["papel"].initial = papeis[0] if papeis else None
        self.fields["papel"].widget.attrs["x-model"] = "papel"
        self.fields["especialidade"].choices = [("", "Selecione"), *((nome, nome) for nome in especialidades)]

    def clean_senha(self) -> str:
        senha = self.cleaned_data["senha"]
        if len(senha.encode()) > self.LIMITE_BYTES_SENHA:
            raise ValidationError("A senha é longa demais.")
        return senha

    def clean_cpf(self) -> str:
        cpf = re.sub(r"\D", "", self.cleaned_data["cpf"])
        if cpf and len(cpf) != 11:
            raise ValidationError("O CPF deve ter 11 números.")
        return cpf

    def clean_telefone(self) -> str:
        telefone = re.sub(r"\D", "", self.cleaned_data["telefone"])
        if telefone and not 10 <= len(telefone) <= 11:
            raise ValidationError("Informe o DDD e o número, por exemplo (11) 99999-0000.")
        return telefone

    def clean(self) -> dict[str, Any]:
        dados = super().clean()
        for campo in self.CAMPOS_DA_FICHA.get(dados.get("papel"), ()):
            if not dados.get(campo) and campo not in self.errors:
                self.add_error(campo, "Campo obrigatório para este tipo de usuário.")
        return dados

    def dados_para_api(self) -> dict[str, Any]:
        dados = self.cleaned_data
        payload: dict[str, Any] = {key: dados[key] for key in ("nome", "email", "senha", "papel")}
        if dados["papel"] == PACIENTE:
            payload["paciente"] = {
                "cpf": dados["cpf"],
                "data_nascimento": dados["data_nascimento"].isoformat(),
                "telefone": dados["telefone"],
            }
        if dados["papel"] == "medico":
            payload["medico"] = {"crm": dados["crm"], "especialidade": dados["especialidade"]}
        return payload


SITUACOES = (("agendada", "Agendada"), ("realizada", "Realizada"), ("cancelada", "Cancelada"))
MANTER_HORARIO = "Manter o horário atual"


def opcoes_de_horario(horarios: Sequence[HorarioLivre], vazio: str) -> list[tuple[str | int, str]]:
    return [("", vazio), *((horario.id, f"{horario.hora_inicio} às {horario.hora_fim}") for horario in horarios)]


def _opcoes_de_medico(medicos: Sequence[MedicoResumo], vazio: str) -> list[tuple[str | int, str]]:
    return [("", vazio), *((medico.id, f"{medico.nome} ({medico.especialidade})") for medico in medicos)]


def _campo_de_data() -> forms.DateInput:
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def _campo_de_hora() -> forms.TimeInput:
    return forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


def _recarregar_horarios_ao_mudar(form: forms.Form, url_horarios: str) -> None:
    gatilho = {
        "hx-get": url_horarios,
        "hx-target": "#id_horario_id",
        "hx-trigger": "change",
        "hx-include": "[name=medico_id],[name=data]",
    }
    for campo in ("medico_id", "data"):
        form.fields[campo].widget.attrs.update(gatilho)


class FiltroConsultasForm(forms.Form):
    data_inicio = forms.DateField(label="De", required=False, widget=_campo_de_data())
    data_fim = forms.DateField(label="Até", required=False, widget=_campo_de_data())
    medico_id = forms.TypedChoiceField(label="Médico", required=False, coerce=int, empty_value=None)
    status = forms.ChoiceField(label="Situação", required=False, choices=(("", "Todas"), *SITUACOES))

    def __init__(self, *args, medicos: Sequence[MedicoResumo], **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["medico_id"].choices = _opcoes_de_medico(medicos, "Todos")

    def filtros_para_api(self) -> dict[str, str]:
        dados = self.cleaned_data
        filtros = {
            "data_inicio": dados["data_inicio"].isoformat() if dados["data_inicio"] else "",
            "data_fim": dados["data_fim"].isoformat() if dados["data_fim"] else "",
            "medico_id": str(dados["medico_id"] or ""),
            "status": dados["status"],
        }
        return {chave: valor for chave, valor in filtros.items() if valor}


class AgendamentoForm(forms.Form):
    paciente_id = forms.TypedChoiceField(label="Paciente", coerce=int)
    medico_id = forms.TypedChoiceField(label="Médico", coerce=int)
    data = forms.DateField(label="Data", widget=_campo_de_data())
    horario_id = forms.TypedChoiceField(label="Horário", coerce=int)
    observacao = forms.CharField(
        label="Observação", required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(
        self,
        *args,
        pacientes: Sequence[PacienteResumo],
        medicos: Sequence[MedicoResumo],
        horarios: Sequence[HorarioLivre],
        url_horarios: str,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.fields["paciente_id"].choices = [
            ("", "Selecione"),
            *((paciente.id, f"{paciente.nome} (CPF {paciente.cpf_formatado})") for paciente in pacientes),
        ]
        self.fields["medico_id"].choices = _opcoes_de_medico(medicos, "Selecione")
        self.fields["horario_id"].choices = opcoes_de_horario(horarios, "Escolha o médico e a data")
        _recarregar_horarios_ao_mudar(self, url_horarios)

    def dados_para_api(self) -> dict[str, Any]:
        dados = self.cleaned_data
        return {
            "paciente_id": dados["paciente_id"],
            "medico_id": dados["medico_id"],
            "horario_id": dados["horario_id"],
            "data": dados["data"].isoformat(),
            "observacao": dados["observacao"] or None,
        }


class AlteracaoConsultaForm(forms.Form):
    medico_id = forms.TypedChoiceField(label="Médico", coerce=int)
    data = forms.DateField(label="Data", widget=_campo_de_data())
    horario_id = forms.TypedChoiceField(label="Novo horário", required=False, coerce=int, empty_value=None)
    status = forms.ChoiceField(label="Situação", choices=SITUACOES[:2])
    observacao = forms.CharField(
        label="Observação", required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 2})
    )
    confirmado = forms.BooleanField(label="O paciente confirmou a alteração")

    def __init__(
        self, *args, medicos: Sequence[MedicoResumo], horarios: Sequence[HorarioLivre], url_horarios: str, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.fields["medico_id"].choices = _opcoes_de_medico(medicos, "Selecione")
        self.fields["horario_id"].choices = opcoes_de_horario(horarios, MANTER_HORARIO)
        _recarregar_horarios_ao_mudar(self, url_horarios)

    def clean(self) -> dict[str, Any]:
        dados = super().clean()
        if {"medico_id", "data"} & set(self.changed_data) and not dados.get("horario_id"):
            self.add_error("horario_id", "Para mudar o médico ou a data, escolha um novo horário.")
        return dados

    def dados_para_api(self) -> dict[str, Any]:
        dados = self.cleaned_data
        alteracao = {"status": dados["status"], "observacao": dados["observacao"], "confirmado": True}
        if dados["horario_id"]:
            alteracao["horario_id"] = dados["horario_id"]
        return alteracao


class CancelamentoForm(forms.Form):
    prefix = "cancelamento"

    confirmado = forms.BooleanField(label="O paciente confirmou o cancelamento")


class LiberacaoHorariosForm(forms.Form):
    MAXIMO_DE_DIAS = 92
    DIAS_DA_SEMANA = (
        ("0", "Segunda"), ("1", "Terça"), ("2", "Quarta"), ("3", "Quinta"),
        ("4", "Sexta"), ("5", "Sábado"), ("6", "Domingo"),
    )
    DIAS_UTEIS = ["0", "1", "2", "3", "4"]
    DURACOES = (
        ("15", "15 minutos"), ("20", "20 minutos"), ("30", "30 minutos"), ("45", "45 minutos"), ("60", "1 hora")
    )

    medico_id = forms.TypedChoiceField(label="Médico", coerce=int)
    data_inicio = forms.DateField(label="De", widget=_campo_de_data())
    data_fim = forms.DateField(label="Até", widget=_campo_de_data())
    dias_semana = forms.MultipleChoiceField(
        label="Dias da semana", choices=DIAS_DA_SEMANA, widget=forms.CheckboxSelectMultiple, initial=DIAS_UTEIS
    )
    hora_inicio = forms.TimeField(label="Das", widget=_campo_de_hora(), initial="08:00")
    hora_fim = forms.TimeField(label="Até as", widget=_campo_de_hora(), initial="12:00")
    duracao_minutos = forms.TypedChoiceField(
        label="Duração de cada consulta", choices=DURACOES, coerce=int, initial="30"
    )

    def __init__(self, *args, medicos: Sequence[MedicoResumo], medico_inicial: int | None, hoje: date, **kwargs):
        super().__init__(*args, **kwargs)
        self.hoje = hoje
        self.fields["medico_id"].choices = _opcoes_de_medico(medicos, "Selecione")
        self.fields["medico_id"].initial = medico_inicial
        self.fields["data_inicio"].initial = hoje
        self.fields["data_fim"].initial = hoje + timedelta(days=6)

    def clean(self) -> dict[str, Any]:
        dados = super().clean()
        inicio, fim = dados.get("data_inicio"), dados.get("data_fim")
        if inicio and inicio < self.hoje:
            self.add_error("data_inicio", "Escolha hoje ou uma data futura.")
        if inicio and fim and fim < inicio:
            self.add_error("data_fim", "A data final deve ser igual ou posterior à inicial.")
        elif inicio and fim and (fim - inicio).days >= self.MAXIMO_DE_DIAS:
            self.add_error("data_fim", f"Libere no máximo {self.MAXIMO_DE_DIAS} dias por vez.")
        if dados.get("hora_inicio") and dados.get("hora_fim") and dados["hora_fim"] <= dados["hora_inicio"]:
            self.add_error("hora_fim", "O horário final deve ser depois do inicial.")
        return dados

    def dados_para_api(self) -> dict[str, Any]:
        dados = self.cleaned_data
        return {
            "medico_id": dados["medico_id"],
            "data_inicio": dados["data_inicio"].isoformat(),
            "data_fim": dados["data_fim"].isoformat(),
            "dias_semana": [int(dia) for dia in dados["dias_semana"]],
            "hora_inicio": dados["hora_inicio"].strftime("%H:%M"),
            "hora_fim": dados["hora_fim"].strftime("%H:%M"),
            "duracao_minutos": dados["duracao_minutos"],
        }
