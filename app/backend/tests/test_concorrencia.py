"""Cenário C: reservas simultâneas do mesmo horário (bloqueio de linha + índice único parcial).

O último teste roda em PostgreSQL real quando TEST_POSTGRES_URL aponta para um banco DESCARTÁVEL
(as tabelas são recriadas), comprovando que a segunda transação espera o SELECT ... FOR UPDATE.
"""

import os
import threading
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker

from app.backend.core.database import Base, SessionLocal
from app.backend.core.exceptions import HorarioIndisponivelError
from app.backend.main import app
from app.backend.models import Consulta, Horario, Medico, Paciente, StatusConsulta, Usuario
from app.backend.schemas.consulta import ConsultaCreate
from app.backend.services.consulta_service import ConsultaService
from app.backend.tests.helpers import ClinicaApi

MENSAGEM_RESERVADO = "Este horário acabou de ser reservado por outro paciente."


def _preparar_disputa(fabrica_sessao: Callable[[], Session]) -> tuple[list[int], int, int, str]:
    with fabrica_sessao() as db:
        usuarios = [Usuario(nome=f"Paciente {n}", email=f"p{n}@email.com", senha_hash="x") for n in (1, 2)]
        db.add_all(usuarios)
        db.flush()
        pacientes = [
            Paciente(usuario_id=u.id, nome=u.nome, cpf=f"{n:011d}", data_nascimento="1950-01-01", telefone="11999990000")
            for n, u in enumerate(usuarios, start=1)
        ]
        medico = Medico(nome="Dr. Disputa", crm="CRM-SP-9999", especialidade="Cardiologia")
        db.add_all([*pacientes, medico])
        db.flush()
        horario = Horario(medico_id=medico.id, data="2026-11-20", hora_inicio="10:00", hora_fim="10:30")
        db.add(horario)
        db.commit()
        return [p.id for p in pacientes], medico.id, horario.id, horario.data


def _disputar_horario(fabrica_sessao: Callable[[], Session]) -> list[str | HorarioIndisponivelError]:
    paciente_ids, medico_id, horario_id, data = _preparar_disputa(fabrica_sessao)
    largada = threading.Barrier(len(paciente_ids))
    resultados: list[str | HorarioIndisponivelError] = []

    def reservar(paciente_id: int) -> None:
        with fabrica_sessao() as db:
            largada.wait()
            try:
                ConsultaService(db).create(
                    ConsultaCreate(paciente_id=paciente_id, medico_id=medico_id, horario_id=horario_id, data=data)
                )
                resultados.append("agendada")
            except HorarioIndisponivelError as erro:
                resultados.append(erro)

    threads = [threading.Thread(target=reservar, args=(paciente_id,)) for paciente_id in paciente_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    with fabrica_sessao() as db:
        ativas = db.query(Consulta).filter(Consulta.horario_id == horario_id, Consulta.status != StatusConsulta.CANCELADA)
        assert ativas.count() == 1
        assert db.get(Horario, horario_id).disponivel is False
    return resultados


def test_cenario_c_reservas_simultaneas_no_mesmo_horario(banco_limpo: None) -> None:
    resultados = _disputar_horario(SessionLocal)

    assert resultados.count("agendada") == 1
    falhas = [r for r in resultados if isinstance(r, HorarioIndisponivelError)]
    assert len(falhas) == 1
    assert falhas[0].detail == MENSAGEM_RESERVADO


def test_cenario_c_api_retorna_409_amigavel_para_a_segunda_requisicao(api: ClinicaApi) -> None:
    medico = api.cadastrar_medico("Dr. Disputa", "CRM-SP-9999", "Cardiologia")
    horario = api.cadastrar_horario(medico, "2026-11-20", "10:00")
    pacientes = [api.cadastrar_paciente(f"Paciente {n}", f"p{n}@email.com", f"{n:011d}")[1] for n in (1, 2)]
    largada = threading.Barrier(2)
    respostas = []

    def reservar(paciente_id: int) -> None:
        cliente = TestClient(app)
        largada.wait()
        respostas.append(
            cliente.post(
                "/api/consultas",
                headers=api.admin,
                json={"paciente_id": paciente_id, "medico_id": medico, "horario_id": horario, "data": "2026-11-20"},
            )
        )

    threads = [threading.Thread(target=reservar, args=(paciente_id,)) for paciente_id in pacientes]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(resposta.status_code for resposta in respostas) == [201, 409]
    conflito = next(resposta for resposta in respostas if resposta.status_code == 409)
    assert conflito.json() == {"detail": MENSAGEM_RESERVADO}


def test_cenario_c_reserva_emite_select_for_update_no_dialeto_postgresql(api: ClinicaApi) -> None:
    medico = api.cadastrar_medico("Dr. João Mendes", "CRM-SP-1001", "Cardiologia")
    horario = api.cadastrar_horario(medico, "2026-11-10", "09:00")
    _, paciente = api.cadastrar_paciente("Paciente 1", "p1@email.com", "00000000001")
    sql_postgresql: list[str] = []

    def capturar(estado: ORMExecuteState) -> None:
        sql_postgresql.append(str(estado.statement.compile(dialect=postgresql.dialect())))

    with SessionLocal() as db:
        event.listen(db, "do_orm_execute", capturar)
        ConsultaService(db).create(
            ConsultaCreate(paciente_id=paciente, medico_id=medico, horario_id=horario, data="2026-11-10")
        )

    assert any("FROM horarios" in sql and sql.rstrip().endswith("FOR UPDATE") for sql in sql_postgresql)


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="Defina TEST_POSTGRES_URL com um banco PostgreSQL descartável")
def test_cenario_c_bloqueio_de_linha_no_postgresql() -> None:
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        resultados = _disputar_horario(sessionmaker(bind=engine, autoflush=False))
    finally:
        engine.dispose()

    falhas = [r for r in resultados if isinstance(r, HorarioIndisponivelError)]
    assert resultados.count("agendada") == 1 and len(falhas) == 1
    assert falhas[0].detail == MENSAGEM_RESERVADO
    assert falhas[0].__cause__ is None, "a segunda transação deve esperar o lock, não depender do índice único"
