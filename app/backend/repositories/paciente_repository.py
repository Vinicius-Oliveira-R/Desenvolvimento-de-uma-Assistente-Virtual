from sqlalchemy.orm import Session

from app.backend.models import Paciente


class PacienteRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, paciente: Paciente) -> Paciente:
        self.db.add(paciente)
        self.db.commit()
        self.db.refresh(paciente)
        return paciente

    def list_all(self) -> list[Paciente]:
        return self.db.query(Paciente).all()

    def get_by_id(self, paciente_id: int) -> Paciente | None:
        return self.db.query(Paciente).filter(Paciente.id == paciente_id).first()
