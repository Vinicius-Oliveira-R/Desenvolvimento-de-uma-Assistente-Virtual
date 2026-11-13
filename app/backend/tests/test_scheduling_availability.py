"""Integração HTTP/ORM. Usar apenas o banco descartável do conftest, nunca Neon."""
import pytest


def prepare(api, count=3):
    headers, _ = api.cadastrar_paciente('Pessoa de Teste', 'agenda@example.com', '10006172547')
    doctor = api.cadastrar_medico('Dra. Maria Silva', 'CRM-PR-9911', 'Clínica Geral')
    slots = [api.cadastrar_horario(doctor, '2026-11-10', f'{9+i:02d}:00') for i in range(count)]
    return api.conversa(headers), slots


@pytest.mark.parametrize('text', [
    'agendar consulta', 'quero agendar consulta', 'quais dias tem disponiveis',
    'quais dias tem consulta', 'que dia tem vaga', 'qual horario tem', 'horarios livres',
    'quando posso ir', 'não sei', 'não sei qual médico', 'tanto faz', 'quero marcar minha consulta',
])
def test_initial_lay_request_lists_real_general_slots(api, text):
    conversation, slots = prepare(api)
    response = conversation.enviar(text)
    assert response['resultado'] == 'sugestao_horario'
    pending = response['contexto']['acao_pendente']
    assert pending['criterios']['especialidade'] == 'Clínica Geral'
    assert pending['horarios_oferecidos'] == slots[:2 if response['perfil'] == 'IDOSO' else 6]
    assert pending['aguardando_escolha'] is True
    assert pending['horario_id'] is None
    assert all(api.horario_disponivel(pk) for pk in slots)
    assert '09:00' in response['resposta'] and '10:00' in response['resposta']


def test_choice_requires_confirmation_and_books_only_selected(api):
    conversation, slots = prepare(api)
    conversation.enviar('quero marcar consulta')
    conversation.enviar('sim')
    assert all(api.horario_disponivel(pk) for pk in slots)
    selected = conversation.enviar('opção 2')
    assert selected['contexto']['acao_pendente']['horario_id'] == slots[1]
    assert api.horario_disponivel(slots[1])
    confirmed = conversation.enviar('sim')
    assert confirmed['resultado'] == 'consulta_agendada'
    assert not api.horario_disponivel(slots[1])
    assert api.horario_disponivel(slots[0]) and api.horario_disponivel(slots[2])


def test_request_day_without_slots_offers_future_alternatives(api):
    conversation, slots = prepare(api)
    response = conversation.enviar('marcar consulta dia 05/11')
    assert response['resultado'] == 'sugestao_horario'
    assert response['contexto']['acao_pendente']['horarios_oferecidos'] == slots[:2 if response['perfil'] == 'IDOSO' else 6]
    assert 'alternativas' in response['resposta']
    assert all(api.horario_disponivel(pk) for pk in slots)


def test_broad_question_clears_previous_empty_date(api):
    conversation, slots = prepare(api)
    no_slots = conversation.enviar('agendar consulta dia 30/11')
    assert no_slots['resultado'] == 'sem_horarios'
    available = conversation.enviar('quais dias tem disponiveis')
    assert available['contexto']['acao_pendente']['horarios_oferecidos'] == slots[:2 if available['perfil'] == 'IDOSO' else 6]


def test_empty_agenda_does_not_invent_date_or_loop(api):
    conversation, _ = prepare(api, count=0)
    for text in ('agendar consulta','quero agendar consulta','quais dias tem disponiveis'):
        response = conversation.enviar(text)
        assert response['resultado'] == 'sem_horarios'
        assert 'recepção' in response['resposta']
        assert 'dia 20' not in response['resposta']


def test_more_options_does_not_repeat_batch(api):
    conversation, slots = prepare(api, count=8)
    conversation.contexto['preferencia_estilo'] = 'padrao'
    first = conversation.enviar('quais dias tem')
    assert first['contexto']['acao_pendente']['horarios_oferecidos'] == slots[:6]
    second = conversation.enviar('mais horarios')
    assert second['contexto']['acao_pendente']['horarios_oferecidos'] == slots[6:]
    assert all(api.horario_disponivel(pk) for pk in slots)


def test_unknown_number_does_not_create_appointment(api):
    conversation, slots = prepare(api)
    conversation.enviar('marcar consulta')
    response = conversation.enviar('99')
    assert response['resultado'] == 'sugestao_horario'
    assert all(api.horario_disponivel(pk) for pk in slots)


def test_doctor_name_question_keeps_only_requested_doctor(api):
    conversation, slots = prepare(api)
    response = conversation.enviar('Dra. Maria atende quando?')
    assert response['resultado'] == 'sugestao_horario'
    assert response['contexto']['acao_pendente']['horarios_oferecidos'] == slots[:2 if response['perfil'] == 'IDOSO' else 6]


def test_explicit_appointment_also_waits_for_confirmation(api):
    conversation, slots = prepare(api)
    result = conversation.enviar('quero agendar com Dra. Maria dia 10/11 às 10h')
    assert result['resultado'] == 'sugestao_horario'
    assert result['contexto']['acao_pendente']['horario_id'] == slots[1]
    assert all(api.horario_disponivel(pk) for pk in slots)
    assert conversation.enviar('sim')['resultado'] == 'consulta_agendada'


def test_confirmation_can_use_existing_affirmation(api):
    conversation, slots = prepare(api, count=1)
    conversation.enviar('marcar consulta')
    assert conversation.enviar('pode ser')['resultado'] == 'consulta_agendada'
    assert not api.horario_disponivel(slots[0])
