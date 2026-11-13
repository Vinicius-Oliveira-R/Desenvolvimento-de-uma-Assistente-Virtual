def test_simple_fallback_keeps_explicit_outside_period_notice(api):
    from app.backend.assistant.concise_responses import response_units
    patient, _ = api.cadastrar_paciente('Pessoa', 'outside@example.com', '00000000001')
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-TEST-631', 'Clínica Geral')
    slot = api.cadastrar_horario(doctor, '2026-11-10', '09:00')
    conversation = api.conversa(patient)
    conversation.enviar('modo simples')
    response = conversation.enviar('marcar consulta amanhã')
    assert 'fora do período pedido' in response['resposta']
    assert 'Clínica Geral' in response['resposta']
    assert response_units(response['resposta']) <= 3
    assert api.horario_disponivel(slot)
