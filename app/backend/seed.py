"""Popula o banco com dados de demonstração. Idempotente: pode ser executado mais de uma vez.

Uso: python -m app.backend.seed
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from app.backend.core.clock import get_clock
from app.backend.core.database import Base, SessionLocal, engine
from app.backend.core.security import get_password_hash
from app.backend.models import Horario, Medico, Paciente, PapelUsuario, Usuario

SENHA_DEMO = "senha123"
FUNCIONARIOS = (
    ("Recepção da Clínica", "recepcao@clinica.com", PapelUsuario.ADMIN),
    ("Dr. João Mendes", "joao.mendes@clinica.com", PapelUsuario.MEDICO),
)
PACIENTES = (
    ("Lurdes Andrade", "lurdes@clinica.com", "12345678901", "1948-05-12"),
    ("Carlos Pereira", "carlos@clinica.com", "12345678902", "1990-08-21"),
)
MEDICOS = (
    ("Dr. João Mendes", "CRM-SP-100001", "Cardiologia"),
    ("Dra. Maria Silva", "CRM-SP-100002", "Clínica Geral"),
    ("Dra. Ana Costa", "CRM-SP-100003", "Dermatologia"),
    ("Dr. Carlos Lima", "CRM-SP-100004", "Ortopedia"),
)
HORAS = ("08:00", "09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00")
DIAS_DE_AGENDA = 365


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for nome, email, papel in FUNCIONARIOS:
            _obter_ou_criar_usuario(db, nome, email, papel)
        for nome, email, cpf, nascimento in PACIENTES:
            usuario = _obter_ou_criar_usuario(db, nome, email, PapelUsuario.PACIENTE)
            if db.query(Paciente).filter(Paciente.usuario_id == usuario.id).first() is None:
                db.add(Paciente(usuario_id=usuario.id, nome=nome, cpf=cpf, data_nascimento=nascimento, telefone="11999990000"))

        medicos = []
        for nome, crm, especialidade in MEDICOS:
            medico = db.query(Medico).filter(Medico.crm == crm).first()
            if medico is None:
                medico = Medico(nome=nome, crm=crm, especialidade=especialidade)
                db.add(medico)
            medicos.append(medico)
        db.flush()

        existentes = set(db.query(Horario.medico_id, Horario.data, Horario.hora_inicio).all())
        hoje = get_clock().today()
        dias_uteis = [dia for dia in (hoje + timedelta(days=n) for n in range(1, DIAS_DE_AGENDA + 1)) if dia.weekday() < 5]
        novos = [
            Horario(medico_id=medico.id, data=dia.isoformat(), hora_inicio=hora, hora_fim=f"{hora[:2]}:30")
            for dia in dias_uteis
            for medico in medicos
            for hora in HORAS
            if (medico.id, dia.isoformat(), hora) not in existentes
        ]
        db.add_all(novos)
        db.commit()

    usuarios = [(email, papel) for _, email, papel in FUNCIONARIOS]
    usuarios += [(email, PapelUsuario.PACIENTE) for _, email, _, _ in PACIENTES]
    print(f"Seed concluído: {len(novos)} horários criados.")
    print(f"Usuários de demonstração (senha '{SENHA_DEMO}'): " + ", ".join(f"{e} ({p})" for e, p in usuarios))


def _obter_ou_criar_usuario(db: Session, nome: str, email: str, papel: PapelUsuario) -> Usuario:
    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None:
        usuario = Usuario(nome=nome, email=email, senha_hash=get_password_hash(SENHA_DEMO), papel=papel)
        db.add(usuario)
        db.flush()
    return usuario


if __name__ == "__main__":
    main()
