from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView

from assistant.api_client import ApiError
from assistant.profile_forms import ContatoPacienteForm
from assistant.mixins import ClinicaApiMixin


class ContatoPacienteView(ClinicaApiMixin, TemplateView):
    template_name = "equipe/contato_paciente.html"
    papeis_permitidos = frozenset({"paciente", "admin", "medico"})

    async def get(self, request, paciente_id=None, **kwargs):
        return await self._atender(request, paciente_id)

    async def post(self, request, paciente_id=None, **kwargs):
        return await self._atender(request, paciente_id, request.POST)

    async def _atender(self, request, paciente_id, dados=None):
        client = self.get_api_client()
        try:
            contact = await client.get_patient_contact(self.token, paciente_id)
        except ApiError as exc:
            return self.render_to_response(self.get_context_data(erro=exc.mensagem), status=exc.status_code or 503)
        form = ContatoPacienteForm(dados, initial=contact)
        if dados is not None and form.is_valid():
            try:
                await client.update_patient_contact(self.token, form.cleaned_data, paciente_id)
            except ApiError as exc:
                form.add_error(None, exc.mensagem)
            else:
                messages.success(request, "Contato atualizado; utilize o novo e-mail no próximo login.")
                return redirect(request.path)
        return self.render_to_response(self.get_context_data(form=form, nome=contact["nome"]))


class ProfissionaisView(ClinicaApiMixin, TemplateView):
    template_name = "equipe/profissionais.html"
    papeis_permitidos = frozenset({"gestor"})

    async def get(self, request, **kwargs):
        try:
            doctors = await self.get_api_client().list_doctor_records(self.token)
        except ApiError as exc:
            return self.render_to_response(self.get_context_data(erro=exc.mensagem), status=503)
        return self.render_to_response(self.get_context_data(medicos=doctors))

    async def post(self, request, **kwargs):
        try:
            doctor_id = int(request.POST.get("medico_id", ""))
            if doctor_id <= 0 or request.POST.get("ativo") not in ("true", "false"):
                return HttpResponse(status=400)
            await self.get_api_client().set_doctor_active(self.token, doctor_id, request.POST["ativo"] == "true")
        except ValueError:
            return HttpResponse(status=400)
        except ApiError as exc:
            messages.error(request, exc.mensagem)
        else:
            messages.success(request, "Situação do profissional atualizada; consultas existentes foram preservadas.")
        return redirect("profissionais")
