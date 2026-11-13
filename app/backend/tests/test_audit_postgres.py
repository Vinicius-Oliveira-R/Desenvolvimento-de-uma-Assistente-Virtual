"""Integração somente com PostgreSQL DESCARTÁVEL; não aponta ao Neon de produção."""
import os
import threading

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.backend.core.database import Base
from app.backend.core.exceptions import ConflictError
from app.backend.migrate import upgrade
from app.backend.models import Horario, Medico
from app.backend.schemas.horario import HorarioCreate
from app.backend.services.horario_service import HorarioService

pytestmark = pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="Requer PostgreSQL descartável")


@pytest.fixture
def pg():
    engine = create_engine(os.environ["TEST_POSTGRES_URL"])
    # Recria SOMENTE o banco explicitamente reservado aos testes.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def doctor(engine):
    with Session(engine) as db:
        item = Medico(nome="Profissional sintético", crm="CRM-TEST-123", especialidade="Clínica Geral")
        db.add(item)
        db.commit()
        return item.id


def test_postgresql_exclusion_blocks_overlap_even_outside_service(pg):
    pk = doctor(pg)
    with Session(pg) as db:
        db.add(Horario(medico_id=pk, data="2026-11-20", hora_inicio="09:00", hora_fim="09:30"))
        db.commit()
        db.add(Horario(medico_id=pk, data="2026-11-20", hora_inicio="09:15", hora_fim="09:45"))
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert error.value.orig.sqlstate == "23P01"
        db.rollback()
        db.add(Horario(medico_id=pk, data="2026-11-20", hora_inicio="09:30", hora_fim="10:00"))
        db.commit()
        assert db.query(Horario).count() == 2


def test_postgresql_concurrent_generation_commits_only_one_intersection(pg):
    pk = doctor(pg)
    factory = sessionmaker(pg)
    barrier = threading.Barrier(2)
    results = []
    errors = []
    def generate(start, end):
        try:
            with factory() as db:
                barrier.wait(timeout=10)
                try:
                    HorarioService(db).create(HorarioCreate(medico_id=pk, data="2026-11-20", hora_inicio=start, hora_fim=end))
                    results.append("created")
                except ConflictError:
                    results.append("conflict")
        except Exception as exc:
            errors.append(type(exc).__name__)
    workers = [threading.Thread(target=generate, args=pair) for pair in [("09:00", "09:30"), ("09:15", "09:45")]]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
    assert not any(worker.is_alive() for worker in workers)
    assert errors == []
    assert sorted(results) == ["conflict", "created"]
    with Session(pg) as db:
        assert db.query(Horario).count() == 1


def test_postgresql_migration_upgrades_legacy_schema_preserving_rows(pg):
    pk = doctor(pg)
    with pg.begin() as conn:
        conn.execute(text("INSERT INTO usuarios (nome,email,senha_hash,papel,data_criacao) VALUES ('Sintético','migration@example.test','fakehash','paciente','2026-11-01')"))
        conn.execute(text("ALTER TABLE usuarios DROP COLUMN ativo"))
        conn.execute(text("ALTER TABLE usuarios DROP COLUMN token_version"))
        conn.execute(text("ALTER TABLE medicos DROP COLUMN ativo"))
        conn.execute(text("ALTER TABLE horarios DROP CONSTRAINT ex_horario_sem_sobreposicao"))
    upgrade(pg, apply=False)
    assert "ativo" not in {c["name"] for c in inspect(pg).get_columns("usuarios")}
    upgrade(pg, apply=True)
    upgrade(pg, apply=True)
    with pg.connect() as conn:
        assert conn.execute(text("SELECT ativo,token_version FROM usuarios WHERE email='migration@example.test'")).one() == (True, 0)
        assert conn.execute(text("SELECT ativo FROM medicos WHERE id=:id"), {"id": pk}).scalar_one() is True
        assert conn.execute(text("SELECT count(*) FROM pg_constraint WHERE conname='ex_horario_sem_sobreposicao' AND conrelid='horarios'::regclass")).scalar_one() == 1


def test_postgresql_migration_rolls_back_on_preexisting_overlap(pg):
    pk = doctor(pg)
    with pg.begin() as conn:
        conn.execute(text("ALTER TABLE horarios DROP CONSTRAINT ex_horario_sem_sobreposicao"))
        conn.execute(text("ALTER TABLE usuarios DROP COLUMN token_version"))
        conn.execute(text("INSERT INTO horarios (medico_id,data,hora_inicio,hora_fim,disponivel) VALUES (:id,'2026-11-20','09:00','09:30',true), (:id,'2026-11-20','09:15','09:45',true)"), {"id": pk})
    with pytest.raises(RuntimeError, match="sobrepostos"):
        upgrade(pg, apply=True)
    assert "token_version" not in {c["name"] for c in inspect(pg).get_columns("usuarios")}
    with pg.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM horarios")).scalar_one() == 2
