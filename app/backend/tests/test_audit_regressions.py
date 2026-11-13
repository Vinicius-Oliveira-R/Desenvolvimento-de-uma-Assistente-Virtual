"""Regressões da auditoria: usa SOMENTE bancos descartáveis do conftest."""
import threading
import time
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.backend.core.config import Settings, get_settings
from app.backend.core.database import Base, SessionLocal
from app.backend.core.security import create_access_token, get_password_hash, verify_password
from app.backend.core.validation import normalize_cpf, normalize_birth_date
from app.backend.create_gestor import configure_manager
from app.backend.migrate import upgrade
from app.backend.ml.resilience import BoundedPredictor
from app.backend.models import Consulta, Horario, Medico, PapelUsuario, Usuario
from app.backend.services.login_throttle import LoginThrottle
from app.backend.tests.helpers import SENHA_PADRAO


@pytest.mark.parametrize('path', ['interpret', 'agendar', 'recomendar', 'chat'])
def test_all_assistant_routes_require_identity(api, path):
    response = api.client.post('/api/assistant/' + path, json={'mensagem': 'marcar consulta'})
    assert response.status_code == 401


def test_retired_write_never_reserves(api):
    assert api.client.post('/api/assistant/agendar', headers=api.admin,
                           json={'mensagem': 'agendar consulta'}).status_code == 410
    with SessionLocal() as db:
        assert db.query(Consulta).count() == 0


def test_disabled_user_and_old_token_are_rejected(api):
    user = api.cadastrar_usuario('Pessoa', 'disable@example.com')
    token = api.cabecalho_de(user['id'])
    assert api.client.get('/api/auth/me', headers=token).status_code == 200
    with SessionLocal() as db:
        db.get(Usuario, user['id']).ativo = False
        db.commit()
    assert api.client.get('/api/auth/me', headers=token).status_code == 401
    assert api.client.post('/api/auth/login', json={'email': user['email'], 'senha': SENHA_PADRAO}).status_code == 401
    with SessionLocal() as db:
        person = db.get(Usuario, user['id'])
        person.ativo, person.token_version = True, 1
        db.commit()
    assert api.client.get('/api/auth/me', headers=token).status_code == 401
    session = api.client.post('/api/auth/login', json={'email': user['email'], 'senha': SENHA_PADRAO})
    assert session.status_code == 200
    assert api.client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + session.json()['token']}).status_code == 200


@pytest.mark.parametrize('change', [
    {'secret_key': 'too-short'}, {'secret_key': 'x'*64}, {'access_token_expire_minutes': 481},
    {'access_token_expire_minutes': 0}, {'algorithm': 'none'}, {'bcrypt_rounds': 11},
])
def test_settings_reject_unsafe_values(change):
    values = dict(database_url='sqlite:////tmp/test.db', secret_key='test-only-92837465abcdefgh-ABCDEFGH-no-production')
    values.update(change)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_manager_creation_is_initial_only_and_never_promotes(api):
    email = 'ordinary@example.com'
    ordinary = api.cadastrar_usuario('Pessoa', email)
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            configure_manager(db, 'Gestor', email, 'different-test-password-9463')
        db.rollback()
        assert db.get(Usuario, ordinary['id']).papel == PapelUsuario.PACIENTE
        manager = configure_manager(db, 'Gestor Inicial', 'manager@example.com', 'test-manager-password-9276')
        db.commit()
        manager_id = manager.id
    with SessionLocal() as db:
        with pytest.raises(ValueError):
            configure_manager(db, 'Segundo', 'second@example.com', 'another-test-password-9473')
        db.rollback()
        configure_manager(db, 'unused', 'manager@example.com', 'changed-test-password-2847', reset=True)
        db.commit()
        manager = db.get(Usuario, manager_id)
        assert manager.token_version == 1
        assert verify_password('changed-test-password-2847', manager.senha_hash)
        assert manager.nome == 'Gestor Inicial'


@pytest.mark.parametrize('cpf', ['11111111111', 'abcdefghijk', '12345678900', '1234567890', '１２３４５６７８９０９'])
def test_cpf_invalid_inputs_are_rejected(cpf):
    with pytest.raises(ValueError):
        normalize_cpf(cpf)


def test_cpf_accepts_formatted_check_digits():
    assert normalize_cpf('123.456.789-09') == '12345678909'


@pytest.mark.parametrize('value', ['2026-02-30', '2999-01-01', '31/01/2000'])
def test_birth_date_is_real_iso_and_not_future(value):
    with pytest.raises(ValueError):
        normalize_birth_date(value)


def test_contact_edits_are_scoped_and_cannot_change_roles(api):
    first, patient_id = api.cadastrar_paciente('Primeira', 'first@example.com', '00000000001')
    other, _ = api.cadastrar_paciente('Outra', 'other@example.com', '00000000002')
    path = f'/api/cadastros/pacientes/{patient_id}'
    assert api.client.patch(path, headers=other, json={'telefone': '11988887777'}).status_code == 403
    assert api.client.patch(path, json={'telefone': '11988887777'}).status_code == 401
    assert api.client.patch(path, headers=first, json={'papel': 'gestor'}).status_code == 422
    updated = api.client.patch(path, headers=first, json={'email': 'new@example.com', 'telefone': '(11) 98888-7777'})
    assert updated.status_code == 200
    assert updated.json()['telefone'] == '11988887777'
    assert api.client.get('/api/cadastros/pacientes/me', headers=first).json()['email'] == 'new@example.com'
    assert api.client.patch(path, headers=api.admin, json={'email': 'other@example.com'}).status_code == 409
    assert api.client.post('/api/auth/login', json={'email': 'new@example.com', 'senha': SENHA_PADRAO}).status_code == 200


def test_manager_controls_active_state_without_erasing_history(api):
    manager = api.criar_usuario_no_banco('Gestor', 'gestor@example.com', PapelUsuario.GESTOR)
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-PR-867', 'Clínica Geral')
    slot = api.cadastrar_horario(doctor, '2026-11-10', '09:00')
    assert api.client.patch(f'/api/cadastros/medicos/{doctor}', headers=api.admin, json={'ativo': False}).status_code == 403
    assert api.client.patch(f'/api/cadastros/medicos/{doctor}', headers=manager, json={'ativo': False}).status_code == 200
    patient, _ = api.cadastrar_paciente('Pessoa', 'active@example.com', '00000000001')
    reply = api.conversa(patient).enviar('marcar consulta')
    assert reply['resultado'] == 'sem_horarios'
    with SessionLocal() as db:
        assert db.get(Horario, slot) is not None
    assert api.client.patch(f'/api/cadastros/medicos/{doctor}', headers=manager, json={'ativo': True}).status_code == 200
    assert api.conversa(patient).enviar('marcar consulta')['resultado'] == 'sugestao_horario'


def test_overlap_rejected_and_adjacent_slot_allowed(api):
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-PR-123', 'Clínica Geral')
    api.cadastrar_horario(doctor, '2026-11-10', '08:00')
    def post(start, end):
        return api.client.post('/api/horarios', headers=api.admin, json={
            'medico_id': doctor, 'data': '2026-11-10', 'hora_inicio': start, 'hora_fim': end})
    assert post('08:15', '08:45').status_code == 409
    assert post('07:45', '08:15').status_code == 409
    assert post('08:00', '09:00').status_code == 409
    assert post('08:30', '09:00').status_code == 201
    with SessionLocal() as db:
        assert db.query(Horario).count() == 2


def test_conflicting_batch_rolls_back_all_and_does_not_free_booked_slot(api):
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-PR-124', 'Clínica Geral')
    slot = api.cadastrar_horario(doctor, '2026-11-10', '09:00')
    with SessionLocal() as db:
        db.get(Horario, slot).disponivel = False
        db.commit()
    payload = {'medico_id': doctor, 'data_inicio': '2026-11-10', 'data_fim': '2026-11-10',
               'dias_semana': [1], 'hora_inicio': '08:15', 'hora_fim': '10:15', 'duracao_minutos': 30}
    assert api.client.post('/api/horarios/lote', headers=api.admin, json=payload).status_code == 409
    with SessionLocal() as db:
        assert db.query(Horario).count() == 1
        assert db.get(Horario, slot).disponivel is False
    payload.update(hora_inicio='09:00', hora_fim='09:30')
    assert api.client.post('/api/horarios/lote', headers=api.admin, json=payload).json() == {'criados': 0, 'ja_existentes': 1}
    with SessionLocal() as db:
        assert db.get(Horario, slot).disponivel is False


def test_database_itself_rejects_overlapping_rows(api):
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-PR-125', 'Clínica Geral')
    api.cadastrar_horario(doctor, '2026-11-10', '09:00')
    with SessionLocal() as db:
        db.add(Horario(medico_id=doctor, data='2026-11-10', hora_inicio='09:15', hora_fim='09:45'))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_migration_is_idempotent_on_fresh_disposable_database():
    target = create_engine('sqlite:///:memory:')
    try:
        upgrade(target, apply=False)
        assert inspect(target).get_table_names() == []
        upgrade(target, apply=True)
        upgrade(target, apply=True)
        assert {'ativo', 'token_version'} <= {c['name'] for c in inspect(target).get_columns('usuarios')}
        with target.connect() as conn:
            assert conn.execute(text('SELECT count(*) FROM app_schema_revisions')).scalar_one() == 1
    finally:
        target.dispose()


def test_migration_refuses_existing_conflicts_without_deleting():
    target = create_engine('sqlite:///:memory:')
    try:
        with target.begin() as conn:
            conn.execute(text('CREATE TABLE horarios (id INTEGER, medico_id INTEGER, data TEXT, hora_inicio TEXT, hora_fim TEXT)'))
            conn.execute(text("INSERT INTO horarios VALUES (1,1,'2026-11-10','09:00','09:30'), (2,1,'2026-11-10','09:15','09:45')"))
        with pytest.raises(RuntimeError):
            upgrade(target, apply=True)
        with target.connect() as conn:
            assert conn.execute(text('SELECT count(*) FROM horarios')).scalar_one() == 2
    finally:
        target.dispose()


def test_login_limit_is_persistent_and_window_expires(api):
    settings = get_settings().model_copy(update={'login_max_attempts': 2, 'login_ip_max_attempts': 10, 'login_window_seconds': 60})
    with SessionLocal() as db:
        for _ in range(2):
            LoginThrottle(db, settings, lambda: 1000).consume('person@example.com', '127.0.0.1')
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as err:
            LoginThrottle(db, settings, lambda: 1001).consume('PERSON@example.com', '127.0.0.1')
        assert err.value.status_code == 429
        assert int(err.value.headers['Retry-After']) > 0
        LoginThrottle(db, settings, lambda: 1061).consume('person@example.com', '127.0.0.1')


def test_login_http_429_does_not_expose_account(api, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, 'login_max_attempts', 2)
    for _ in range(2):
        assert api.client.post('/api/auth/login', json={'email': 'unknown@example.com', 'senha': 'wrong-password'}).status_code == 401
    blocked = api.client.post('/api/auth/login', json={'email': 'unknown@example.com', 'senha': 'wrong-password'})
    assert blocked.status_code == 429
    assert 'Retry-After' in blocked.headers
    assert 'unknown' not in blocked.text


@pytest.mark.parametrize('kind', ['load', 'predict', 'nan', 'outside'])
def test_ml_failure_keeps_agenda_available(api, monkeypatch, caplog, kind):
    import app.backend.assistant.orchestrator as module
    monkeypatch.setattr(module, 'predictor', BoundedPredictor())
    def load():
        if kind == 'load':
            raise RuntimeError('DO_NOT_LOG_PRIVATE_MESSAGE')
        def predict(_):
            if kind == 'predict':
                raise RuntimeError('DO_NOT_LOG_PRIVATE_MESSAGE')
            return SimpleNamespace(probabilidade_idoso=float('nan') if kind == 'nan' else 2.0)
        return SimpleNamespace(predict=predict)
    monkeypatch.setattr(module, 'get_profile_classifier', load)
    patient, _ = api.cadastrar_paciente('Pessoa', 'ml@example.com', '00000000001')
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-PR-126', 'Clínica Geral')
    slot = api.cadastrar_horario(doctor, '2026-11-10', '09:00')
    conversation = api.conversa(patient)
    result = conversation.enviar('marcar consulta')
    assert result['perfil'] == 'PADRAO' and result['modo_degradado'] is True
    assert result['resultado'] == 'sugestao_horario'
    assert conversation.enviar('sim')['resultado'] == 'consulta_agendada'
    assert not api.horario_disponivel(slot)
    assert 'DO_NOT_LOG_PRIVATE_MESSAGE' not in caplog.text


def test_ml_timeout_does_not_spawn_unbounded_workers():
    predictor = BoundedPredictor()
    release = threading.Event()
    calls = []
    def slow():
        calls.append(1)
        release.wait(2)
        return SimpleNamespace(probabilidade_idoso=0.5)
    try:
        started = time.monotonic()
        assert predictor.call(slow, .01, 60) is None
        assert time.monotonic() - started < .5
        for _ in range(10):
            assert predictor.call(slow, .01, 60) is None
        assert len(calls) == 1
    finally:
        release.set()


def test_simple_style_has_at_most_three_units_and_pages_without_loss(api):
    from app.backend.assistant.concise_responses import response_units
    patient, _ = api.cadastrar_paciente('Pessoa', 'simple@example.com', '00000000001')
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-PR-127', 'Clínica Geral')
    slots = [api.cadastrar_horario(doctor, '2026-11-10', f'{9+i:02d}:00') for i in range(5)]
    conversation = api.conversa(patient)
    conversation.enviar('modo simples')
    seen = []
    for request in ('marcar consulta', 'mais horários', 'mais horários'):
        result = conversation.enviar(request)
        assert result['perfil'] == 'IDOSO'
        assert response_units(result['resposta']) <= 3, result['resposta']
        seen += result['contexto']['acao_pendente']['horarios_oferecidos']
    assert seen == slots
    assert all(api.horario_disponivel(pk) for pk in slots)
    assert conversation.enviar('modo padrão')['perfil'] == 'PADRAO'


def test_atomic_rescheduling_by_patient_preserves_old_until_confirm(api):
    headers, patient_id = api.cadastrar_paciente('Pessoa', 'move@example.com', '00000000001')
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-PR-128', 'Clínica Geral')
    old = api.cadastrar_horario(doctor, '2026-11-10', '09:00')
    new = api.cadastrar_horario(doctor, '2026-11-11', '10:00')
    appointment = api.client.post('/api/consultas', headers=api.admin, json={'paciente_id': patient_id, 'medico_id': doctor, 'horario_id': old, 'data': '2026-11-10'}).json()
    conversation = api.conversa(headers)
    response = conversation.enviar('quero remarcar minha consulta')
    assert response['contexto']['acao_pendente']['tipo'] == 'remarcar'
    response = conversation.enviar('dia 11/11 às 10h')
    assert response['contexto']['acao_pendente']['horario_id'] == new
    assert not api.horario_disponivel(old) and api.horario_disponivel(new)
    result = conversation.enviar('sim')
    assert result['resultado'] == 'remarcacao_aceita'
    assert result['consulta']['id'] == appointment['id']
    assert api.horario_disponivel(old) and not api.horario_disponivel(new)
    with SessionLocal() as db:
        assert db.query(Consulta).count() == 1


def test_failed_rescheduling_keeps_original_and_rejects_other_patient(api):
    from app.backend.services.consulta_service import ConsultaService
    from app.backend.core.exceptions import DomainError
    headers, patient = api.cadastrar_paciente('Pessoa', 'keep@example.com', '00000000001')
    _, other = api.cadastrar_paciente('Outra', 'keep-other@example.com', '00000000002')
    doctor = api.cadastrar_medico('Dra. Teste', 'CRM-PR-129', 'Clínica Geral')
    old = api.cadastrar_horario(doctor, '2026-11-10', '09:00')
    new = api.cadastrar_horario(doctor, '2026-11-11', '10:00')
    ids = []
    for patient_id, slot, day in [(patient, old, '2026-11-10'), (other, new, '2026-11-11')]:
        ids.append(api.client.post('/api/consultas', headers=api.admin, json={'paciente_id': patient_id, 'medico_id': doctor, 'horario_id': slot, 'data': day}).json()['id'])
    with SessionLocal() as db:
        for actor in (patient, other):
            with pytest.raises(DomainError):
                ConsultaService(db).reschedule_for_patient(ids[0], actor, new, old)
        original = db.get(Consulta, ids[0])
        assert original.horario_id == old and original.status == 'agendada'
        assert not db.get(Horario, old).disponivel
