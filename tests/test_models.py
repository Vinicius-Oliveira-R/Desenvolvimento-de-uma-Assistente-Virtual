import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models import Consulta, Horario, Medico, Paciente, Usuario


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_usuario_paciente_medico_relacionamentos(db_session: Session) -> None:
    usuario = Usuario(nome="Ana", email="ana@email.com", senha_hash="hash123", tipo="paciente")
    db_session.add(usuario)
    db_session.commit()

    paciente = Paciente(
        usuario_id=usuario.id,
        nome="Ana Souza",
        cpf="12345678900",
        data_nascimento="1990-01-15",
        telefone="11999999999",
    )
    db_session.add(paciente)
    db_session.commit()

    medico = Medico(nome="Dr. João", crm="CRM-SP-12345", especialidade="Cardiologia")
    db_session.add(medico)
    db_session.commit()

    horario = Horario(medico_id=medico.id, data="2026-10-10", hora_inicio="09:00", hora_fim="09:30", disponivel=True)
    db_session.add(horario)
    db_session.commit()

    consulta = Consulta(
        paciente_id=paciente.id,
        medico_id=medico.id,
        horario_id=horario.id,
        data="2026-10-10",
        status="agendada",
        observacao="Primeira consulta",
    )
    db_session.add(consulta)
    db_session.commit()

    assert consulta.paciente_id == paciente.id
    assert consulta.medico_id == medico.id
    assert consulta.horario_id == horario.id
    assert paciente.usuario_id == usuario.id
    assert medico.horarios[0].id == horario.id


def test_consulta_nao_permite_mesmo_horario_para_mesmo_medico(db_session: Session) -> None:
    usuario = Usuario(nome="Luis", email="luis@email.com", senha_hash="hash456", tipo="paciente")
    db_session.add(usuario)
    db_session.commit()

    paciente = Paciente(
        usuario_id=usuario.id,
        nome="Luis Silva",
        cpf="98765432100",
        data_nascimento="1988-05-20",
        telefone="11888888888",
    )
    db_session.add(paciente)
    db_session.commit()

    medico = Medico(nome="Dra. Maria", crm="CRM-SP-67890", especialidade="Neurologia")
    db_session.add(medico)
    db_session.commit()

    horario = Horario(medico_id=medico.id, data="2026-10-12", hora_inicio="14:00", hora_fim="14:30", disponivel=True)
    db_session.add(horario)
    db_session.commit()

    consulta1 = Consulta(paciente_id=paciente.id, medico_id=medico.id, horario_id=horario.id, data="2026-10-12", status="agendada")
    db_session.add(consulta1)
    db_session.commit()

    consulta2 = Consulta(paciente_id=paciente.id, medico_id=medico.id, horario_id=horario.id, data="2026-10-12", status="agendada")
    db_session.add(consulta2)

    with pytest.raises(IntegrityError):
        db_session.commit()
