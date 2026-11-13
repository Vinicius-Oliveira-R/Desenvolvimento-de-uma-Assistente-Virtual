import json

import httpx
from django.test import TestCase
from django.urls import reverse

from assistant.api_client import ClinicaApiClient
from assistant.tests import ApiFalsaMixin

CONTACT = {"id": 3, "nome": "Paciente de teste", "email": "old@example.com", "telefone": "11999990000"}
DOCTOR = {"id": 8, "nome": "Profissional de teste", "crm": "CRM-TEST-123", "especialidade": "Clínica Geral", "ativo": True}


class ContactManagementTests(ApiFalsaMixin, TestCase):
    def test_contact_requires_login(self):
        response = self.client.get(reverse("meus_dados"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_patient_views_and_edits_own_contact(self):
        self.autenticar()
        requests = self.usar_api(lambda _: httpx.Response(200, json=CONTACT))
        self.assertContains(self.client.get(reverse("meus_dados")), "old@example.com")
        response = self.client.post(reverse("meus_dados"), {"email": "new@example.com", "telefone": "(11) 98888-7777"})
        self.assertRedirects(response, reverse("meus_dados"), fetch_redirect_response=False)
        self.assertEqual(requests[-1].method, "PATCH")
        self.assertEqual(requests[-1].url.path, "/api/cadastros/pacientes/me")
        self.assertEqual(json.loads(requests[-1].content), {"email": "new@example.com", "telefone": "11988887777"})

    def test_staff_edits_selected_patient(self):
        self.autenticar(papel="admin")
        requests = self.usar_api(lambda _: httpx.Response(200, json=CONTACT))
        url = reverse("editar_contato", args=[3])
        response = self.client.post(url, {"email": "new@example.com", "telefone": "11988887777"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(requests[-1].url.path, "/api/cadastros/pacientes/3")

    def test_invalid_phone_never_sent_for_update(self):
        self.autenticar()
        requests = self.usar_api(lambda _: httpx.Response(200, json=CONTACT))
        response = self.client.post(reverse("meus_dados"), {"email": "new@example.com", "telefone": "abc123"})
        self.assertContains(response, "Telefone inválido")
        self.assertFalse(any(req.method == "PATCH" for req in requests))

    def test_conflict_is_shown_without_success(self):
        self.autenticar()
        self.usar_api(lambda req: httpx.Response(409, json={"detail": "E-mail já cadastrado"}) if req.method == "PATCH" else httpx.Response(200, json=CONTACT))
        response = self.client.post(reverse("meus_dados"), {"email": "new@example.com", "telefone": "11988887777"})
        self.assertContains(response, "E-mail já cadastrado")
        self.assertNotContains(response, "Contato atualizado")

    def test_backend_forbids_contact_from_other_patient(self):
        self.autenticar()
        requests = self.usar_api(lambda _: httpx.Response(403, json={"detail": "Sem permissão"}))
        response = self.client.get(reverse("editar_contato", args=[55]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(requests), 1)

    def test_expired_token_returns_to_login(self):
        self.autenticar()
        self.usar_api(lambda _: httpx.Response(401, json={"detail": "Token expirado"}))
        response = self.client.get(reverse("meus_dados"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)


class ProfessionalManagementTests(ApiFalsaMixin, TestCase):
    def test_manager_can_deactivate_professional(self):
        self.autenticar(papel="gestor")
        requests = self.usar_api(lambda req: httpx.Response(200, json=[DOCTOR] if req.method == "GET" else {**DOCTOR, "ativo": False}))
        self.assertContains(self.client.get(reverse("profissionais")), "Desativar")
        response = self.client.post(reverse("profissionais"), {"medico_id": "8", "ativo": "false"})
        self.assertRedirects(response, reverse("profissionais"), fetch_redirect_response=False)
        self.assertEqual(requests[-1].method, "PATCH")
        self.assertEqual(json.loads(requests[-1].content), {"ativo": False})

    def test_patient_cannot_open_professional_management(self):
        self.autenticar()
        requests = self.usar_api(lambda _: httpx.Response(500))
        response = self.client.get(reverse("profissionais"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(requests, [])

    def test_invalid_action_is_rejected_without_api_write(self):
        self.autenticar(papel="gestor")
        requests = self.usar_api(lambda _: httpx.Response(500))
        response = self.client.post(reverse("profissionais"), {"medico_id": "8", "ativo": "DELETE"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(requests, [])

    async def test_booking_doctor_list_excludes_inactive_records(self):
        client = ClinicaApiClient("https://api.example.test/api", transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=[DOCTOR, {**DOCTOR, "id": 9, "ativo": False}])))
        self.assertEqual([doctor.id for doctor in await client.list_doctors("test-token")], [8])
